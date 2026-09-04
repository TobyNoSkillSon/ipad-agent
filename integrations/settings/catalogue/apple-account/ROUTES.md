# AppleAccount Settings routes

Read this section only when the requested destination belongs here. Raw URLs remain in the machine catalogue. Compatibility is proven only for product `iPad17,1`, hardware `J817AP`, and OS build `23G83`.

`proven` routes are available to ordinary `show` calls on that exact scope. `candidate` routes are retained for explicit, controlled development testing only. `incompatible` routes conflict with this profile or have negative visual evidence. `template` routes contain dynamic placeholders and never dispatch. Safety policy remains separate: `normal`, `explicit`, or `blocked`.

| Route ID | Label | Availability | Scoped evidence | Kind / policy |
|---|---|---|---|---|
| `apple-account` | Apple Account | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / explicit |
| `apple-account-empty` | Settings.Apple Account > | **template** | runtime-literal (iOS 26.5 simulator, 23F77) | dynamic / blocked |
| `apple-account-icloud-service` | Apple Account > iCloud see the iCloud main section for more URLs | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / explicit |
| `apple-account-icloud-service-storage-and-backup-manage-storage` | Settings.Apple Account > ICLOUD SERVICE > STORAGE AND BACKUP > MANAGE STORAGE | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / explicit |
| `apple-account-icloud-service-com-apple-dataclass` | Settings.Apple Account > ICLOUD SERVICE > com.apple.Dataclass | **template** | runtime-literal (iOS 26.5 simulator, 23F77) | dynamic / blocked |
| `apple-account-icloud-service-com-apple-dataclass-cloud-photos` | Settings.Apple Account > ICLOUD SERVICE > com.apple.Dataclass.Cloud Photos | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / explicit |
| `apple-account-icloud-service-com-apple-dataclass-mail` | Settings.Apple Account > ICLOUD SERVICE > com.apple.Dataclass.Mail | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / explicit |
| `apple-account-icloud-service-com-apple-dataclass-mail-empty` | Settings.Apple Account > ICLOUD SERVICE > com.apple.Dataclass.Mail > | **template** | runtime-literal (iOS 26.5 simulator, 23F77) | dynamic / blocked |
| `apple-account-icloud-service-com-apple-dataclass-mail-icloud-mail-cleanup` | Settings.Apple Account > ICLOUD SERVICE > com.apple.Dataclass.Mail > ICLOUD MAIL CLEANUP | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | action / blocked |
| `apple-account-icloud-service-com-apple-dataclass-mail-icloud-mail-cleanup-empty` | Settings.Apple Account > ICLOUD SERVICE > com.apple.Dataclass.Mail > ICLOUD MAIL CLEANUP > | **template** | runtime-literal (iOS 26.5 simulator, 23F77) | dynamic / blocked |
| `apple-account-icloud-service-com-apple-dataclass-messages` | Settings.Apple Account > ICLOUD SERVICE > com.apple.Dataclass.Messages | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / explicit |
| `apple-account-transparency` | Apple Account > Contact Key Verification | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | page / explicit |
| `apple-account-query-aaaction-setup-family` | Settings.Apple Account > aaaction=setup Family | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | action / blocked |
| `apple-account-query-aaaction-show-all-invites` | Settings.Apple Account > aaaction=show All Invites | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | action / blocked |
| `apple-account-query-aaaction-show-family-settings` | Apple Account > Family | **candidate** | runtime-literal (iOS 26.5 simulator, 23F77) | action / blocked |

This section has no ordinary deep-link route for the target profile/build.
