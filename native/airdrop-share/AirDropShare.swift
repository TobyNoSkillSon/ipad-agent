import AppKit
import Darwin
import Foundation

private struct Request {
    let path: String
    let size: Int64
    let device: UInt64
    let inode: UInt64
    let modifiedNanoseconds: Int64
    let changedNanoseconds: Int64
    let maxBytes: Int64
    let timeout: TimeInterval
    let attemptID: String
    let attemptRoot: String
    let sourceBasename: String
    let roots: [String]
    let fileExtension: String
}

private enum RequestError: Error {
    case invalid(String)
}

private func emit(_ value: [String: Any]) {
    guard JSONSerialization.isValidJSONObject(value),
          let data = try? JSONSerialization.data(withJSONObject: value, options: []) else {
        return
    }
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data([0x0a]))
    try? FileHandle.standardOutput.synchronize()
}

private func reject(_ message: String) -> Never {
    emit(["event": "rejected", "message": message])
    exit(2)
}

private func isAttemptID(_ value: String) -> Bool {
    let hex = CharacterSet(charactersIn: "0123456789abcdef")
    return value.utf8.count == 32 && value.unicodeScalars.allSatisfy { hex.contains($0) }
}

private func parseRequest() throws -> Request {
    var singles: [String: String] = [:]
    var roots: [String] = []
    var extensions: [String] = []
    let arguments = Array(CommandLine.arguments.dropFirst())
    var index = 0
    while index < arguments.count {
        let key = arguments[index]
        guard key.hasPrefix("--"), index + 1 < arguments.count else {
            throw RequestError.invalid("invalid helper arguments")
        }
        let value = arguments[index + 1]
        if key == "--root" {
            roots.append(value)
        } else if key == "--extension" {
            extensions.append(value)
        } else {
            guard singles[key] == nil else {
                throw RequestError.invalid("duplicate helper argument \(key)")
            }
            singles[key] = value
        }
        index += 2
    }

    let expected = Set([
        "--path", "--size", "--device", "--inode", "--mtime-ns", "--ctime-ns",
        "--max-bytes", "--timeout",
        "--attempt-id", "--attempt-root", "--source-basename"
    ])
    guard Set(singles.keys) == expected, roots.count == 1, extensions.count == 1 else {
        throw RequestError.invalid("missing or unknown helper arguments")
    }
    guard let path = singles["--path"], path.hasPrefix("/"), !path.contains("\0"),
          let sizeText = singles["--size"], let size = Int64(sizeText), size >= 0,
          let deviceText = singles["--device"], let device = UInt64(deviceText),
          let inodeText = singles["--inode"], let inode = UInt64(inodeText),
          let modifiedText = singles["--mtime-ns"],
          let modifiedNanoseconds = Int64(modifiedText), modifiedNanoseconds >= 0,
          let changedText = singles["--ctime-ns"],
          let changedNanoseconds = Int64(changedText), changedNanoseconds >= 0,
          let maxText = singles["--max-bytes"], let maxBytes = Int64(maxText), maxBytes > 0,
          let timeoutText = singles["--timeout"], let timeout = TimeInterval(timeoutText),
          timeout > 0, timeout <= 600,
          let attemptID = singles["--attempt-id"], isAttemptID(attemptID),
          let attemptRoot = singles["--attempt-root"], attemptRoot.hasPrefix("/"),
          let sourceBasename = singles["--source-basename"],
          !sourceBasename.isEmpty, sourceBasename != ".", sourceBasename != "..",
          !sourceBasename.contains("/"), !sourceBasename.contains("\0"),
          let fileExtension = extensions.first, fileExtension.hasPrefix(".") else {
        throw RequestError.invalid("invalid helper argument value")
    }
    return Request(
        path: path,
        size: size,
        device: device,
        inode: inode,
        modifiedNanoseconds: modifiedNanoseconds,
        changedNanoseconds: changedNanoseconds,
        maxBytes: maxBytes,
        timeout: timeout,
        attemptID: attemptID,
        attemptRoot: attemptRoot,
        sourceBasename: sourceBasename,
        roots: roots,
        fileExtension: fileExtension
    )
}

private func canonicalPath(_ path: String) -> String? {
    guard let pointer = realpath(path, nil) else { return nil }
    defer { free(pointer) }
    return String(cString: pointer)
}

private func isBelow(_ path: String, root: String) -> Bool {
    guard path != root else { return false }
    if root == "/" { return path.hasPrefix("/") }
    return path.hasPrefix(root + "/")
}

private func nanoseconds(_ value: timespec) -> Int64? {
    let seconds = Int64(value.tv_sec)
    let nanos = Int64(value.tv_nsec)
    let (scaled, overflow) = seconds.multipliedReportingOverflow(by: 1_000_000_000)
    guard !overflow else { return nil }
    let (result, addOverflow) = scaled.addingReportingOverflow(nanos)
    return addOverflow ? nil : result
}

private func validate(_ request: Request) throws {
    guard request.roots == [request.attemptRoot] else {
        throw RequestError.invalid("attempt root does not match the sole allowed root")
    }
    guard URL(fileURLWithPath: request.attemptRoot).standardizedFileURL.path == request.attemptRoot,
          canonicalPath(request.attemptRoot) == request.attemptRoot else {
        throw RequestError.invalid("attempt root is not exact and canonical")
    }
    let itemURL = URL(fileURLWithPath: request.path, isDirectory: false)
    guard itemURL.standardizedFileURL.path == request.path,
          canonicalPath(request.path) == request.path,
          itemURL.lastPathComponent == request.sourceBasename,
          itemURL.deletingLastPathComponent().path == request.attemptRoot,
          isBelow(request.path, root: request.attemptRoot) else {
        throw RequestError.invalid("snapshot path or basename is not exact")
    }
    guard request.path.lowercased().hasSuffix(request.fileExtension.lowercased()) else {
        throw RequestError.invalid("snapshot extension is not allowed")
    }

    var rootInfo = Darwin.stat()
    guard lstat(request.attemptRoot, &rootInfo) == 0,
          (rootInfo.st_mode & S_IFMT) == S_IFDIR,
          rootInfo.st_uid == getuid(),
          (rootInfo.st_mode & 0o077) == 0 else {
        throw RequestError.invalid("attempt root is not a private current-user directory")
    }

    var info = Darwin.stat()
    guard lstat(request.path, &info) == 0 else {
        throw RequestError.invalid("cannot stat attempt snapshot")
    }
    guard (info.st_mode & S_IFMT) == S_IFREG,
          info.st_uid == getuid(),
          info.st_nlink == 1,
          (info.st_mode & 0o077) == 0 else {
        throw RequestError.invalid("attempt snapshot is not a private regular file")
    }
    guard Int64(info.st_size) == request.size,
          UInt64(info.st_dev) == request.device,
          UInt64(info.st_ino) == request.inode,
          nanoseconds(info.st_mtimespec) == request.modifiedNanoseconds,
          nanoseconds(info.st_ctimespec) == request.changedNanoseconds else {
        throw RequestError.invalid("attempt snapshot identity or size changed")
    }
    guard info.st_size <= request.maxBytes else {
        throw RequestError.invalid("attempt snapshot exceeds configured size limit")
    }

    let descriptor = open(request.path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW)
    guard descriptor >= 0 else {
        throw RequestError.invalid("attempt snapshot is not safely readable")
    }
    defer { close(descriptor) }
    var opened = Darwin.stat()
    guard fstat(descriptor, &opened) == 0,
          (opened.st_mode & S_IFMT) == S_IFREG,
          opened.st_dev == info.st_dev,
          opened.st_ino == info.st_ino,
          opened.st_size == info.st_size,
          opened.st_mtimespec.tv_sec == info.st_mtimespec.tv_sec,
          opened.st_mtimespec.tv_nsec == info.st_mtimespec.tv_nsec,
          opened.st_ctimespec.tv_sec == info.st_ctimespec.tv_sec,
          opened.st_ctimespec.tv_nsec == info.st_ctimespec.tv_nsec else {
        throw RequestError.invalid("attempt snapshot changed while helper validated it")
    }

    var fileSystem = statfs()
    guard statfs(request.path, &fileSystem) == 0,
          (UInt32(fileSystem.f_flags) & UInt32(MNT_LOCAL)) != 0 else {
        throw RequestError.invalid("attempt snapshot is not on a local filesystem")
    }
}

func hostCompletionResult(
    callbackItems _: [Any],
    nominalSourceBytes: Int64,
    dispatchStarted: TimeInterval
) -> [String: Any] {
    return [
        "event": "completed",
        "nominal_source_bytes": nominalSourceBytes,
        "elapsed_seconds": max(
            0,
            ProcessInfo.processInfo.systemUptime - dispatchStarted
        )
    ]
}

func hostFailureResult(callbackItems _: [Any], error: any Error) -> [String: Any] {
    let nsError = error as NSError
    return [
        "event": "failed",
        "message": nsError.localizedDescription,
        "error_domain": nsError.domain,
        "error_code": nsError.code
    ]
}

final class ShareDelegate: NSObject, NSSharingServiceDelegate {
    private let nominalSourceBytes: Int64
    private let dispatchStarted: TimeInterval
    var result: [String: Any]?
    var finished: Bool { result != nil }

    init(nominalSourceBytes: Int64, dispatchStarted: TimeInterval) {
        self.nominalSourceBytes = nominalSourceBytes
        self.dispatchStarted = dispatchStarted
    }

    func sharingService(_ sharingService: NSSharingService, didShareItems items: [Any]) {
        guard !finished else { return }
        // This delegate is attached only to the sole service and perform() attempt below.
        // Callback item bridging is not additional attempt-identity evidence.
        result = hostCompletionResult(
            callbackItems: items,
            nominalSourceBytes: nominalSourceBytes,
            dispatchStarted: dispatchStarted
        )
    }

    func sharingService(
        _ sharingService: NSSharingService,
        didFailToShareItems items: [Any],
        error: any Error
    ) {
        guard !finished else { return }
        // The callback is bound to this helper's sole service and attempt. Preserve its error.
        result = hostFailureResult(callbackItems: items, error: error)
    }
}

#if !AIRDROP_CALLBACK_TESTING
private let request: Request
do {
    request = try parseRequest()
    try validate(request)
} catch RequestError.invalid(let message) {
    reject(message)
} catch {
    reject("helper validation failed")
}

guard Thread.isMainThread else {
    reject("AppKit helper must run on its main thread")
}
let application = NSApplication.shared
application.setActivationPolicy(.accessory)
application.finishLaunching()

guard let service = NSSharingService(named: .sendViaAirDrop) else {
    reject("sendViaAirDrop sharing service is unavailable")
}
let item = URL(fileURLWithPath: request.path, isDirectory: false)
guard service.canPerform(withItems: [item]) else {
    reject("sendViaAirDrop cannot perform this snapshot request")
}

private let dispatchStarted = ProcessInfo.processInfo.systemUptime
private let deadline = Date(timeIntervalSinceNow: request.timeout)
private let delegate = ShareDelegate(
    nominalSourceBytes: request.size,
    dispatchStarted: dispatchStarted
)
service.delegate = delegate

// The sole send attempt. This flushed marker precedes perform(); any later loss is uncertain.
emit([
    "event": "dispatching",
    "attempt_id": request.attemptID,
    "snapshot_path": request.path,
    "nominal_source_bytes": request.size
])
service.perform(withItems: [item])

while !delegate.finished && Date() < deadline {
    RunLoop.main.run(mode: .default, before: min(deadline, Date(timeIntervalSinceNow: 0.1)))
}
if let result = delegate.result {
    emit(result)
} else {
    emit([
        "event": "uncertain",
        "message": "no NSSSharingService completion or failure callback before timeout"
    ])
    exit(3)
}
#endif
