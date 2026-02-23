# Google Sign-In Setup (iOS SwiftUI)

## 1) Add SDK
- Xcode -> Package Dependencies -> Add:
  - `https://github.com/google/GoogleSignIn-iOS`

## 2) Configure Info.plist
- Copy keys from `design/Auth/GoogleOAuth-Info.plist.template` into your app target `Info.plist`.
- Replace placeholders:
  - `GOOGLE_CLIENT_ID`
  - `GOOGLE_SERVER_CLIENT_ID` (optional but recommended)
  - Reversed client-id URL scheme in `CFBundleURLTypes`

## 3) Wire App Delegate
- In your app entry point:

```swift
import SwiftUI

@main
struct CrewLinkApp: App {
    @UIApplicationDelegateAdaptor(CrewLinkAppDelegate.self) var appDelegate

    var body: some Scene {
        WindowGroup {
            CrewLinkLoginView()
        }
    }
}
```

## 4) URL callback handling
- `CrewLinkAppDelegate` already forwards callback URLs to Google Sign-In via:
  - `GoogleSignInManager.handleOpenURL(_:)`

## 5) Runtime usage
- `CrewLinkLoginView` already calls:
  - `googleSignIn.signIn()`
- On success:
  - `signedInEmail` is populated.
- On failure:
  - `errorMessage` is populated.

## 6) Backend token exchange (recommended)
- After sign-in, send Google ID token / access token to your backend.
- Create your own app session on the server.
