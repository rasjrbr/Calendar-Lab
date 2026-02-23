import SwiftUI
import UIKit
#if canImport(GoogleSignIn)
import GoogleSignIn
#endif

@MainActor
final class GoogleSignInManager: ObservableObject {
    @Published var isLoading = false
    @Published var signedInEmail: String?
    @Published var errorMessage: String?

    func restorePreviousSignIn() {
        #if canImport(GoogleSignIn)
        GIDSignIn.sharedInstance.restorePreviousSignIn { [weak self] user, error in
            guard let self else { return }
            if let error {
                self.errorMessage = "Restore failed: \(error.localizedDescription)"
                return
            }
            self.signedInEmail = user?.profile?.email
        }
        #endif
    }

    func signIn() {
        #if canImport(GoogleSignIn)
        guard let config = GoogleAuthConfig.loadFromBundle() else {
            errorMessage = "Missing GOOGLE_CLIENT_ID in Info.plist."
            return
        }
        GIDSignIn.sharedInstance.configuration = GIDConfiguration(
            clientID: config.clientID,
            serverClientID: config.serverClientID
        )

        guard let presentingVC = Self.topViewController() else {
            errorMessage = "Unable to find presentation context."
            return
        }

        isLoading = true
        errorMessage = nil
        GIDSignIn.sharedInstance.signIn(withPresenting: presentingVC) { [weak self] result, error in
            guard let self else { return }
            self.isLoading = false
            if let error {
                self.errorMessage = "Google sign-in failed: \(error.localizedDescription)"
                return
            }
            self.signedInEmail = result?.user.profile?.email
        }
        #else
        errorMessage = "GoogleSignIn SDK not linked. Add https://github.com/google/GoogleSignIn-iOS"
        #endif
    }

    static func handleOpenURL(_ url: URL) -> Bool {
        #if canImport(GoogleSignIn)
        return GIDSignIn.sharedInstance.handle(url)
        #else
        return false
        #endif
    }

    private static func topViewController(
        base: UIViewController? = UIApplication.shared.connectedScenes
            .compactMap { $0 as? UIWindowScene }
            .flatMap { $0.windows }
            .first(where: \.isKeyWindow)?
            .rootViewController
    ) -> UIViewController? {
        if let nav = base as? UINavigationController {
            return topViewController(base: nav.visibleViewController)
        }
        if let tab = base as? UITabBarController {
            return topViewController(base: tab.selectedViewController)
        }
        if let presented = base?.presentedViewController {
            return topViewController(base: presented)
        }
        return base
    }
}
