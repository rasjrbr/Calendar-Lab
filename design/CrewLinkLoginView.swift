import SwiftUI

struct CrewLinkLoginView: View {
    @State private var email = ""
    @State private var password = ""
    @State private var rememberMe = true
    @State private var authMessage: String?
    @StateObject private var googleSignIn = GoogleSignInManager()

    var body: some View {
        GeometryReader { geo in
            let showHero = geo.size.width >= 900

            HStack(spacing: 0) {
                if showHero {
                    heroPane
                        .frame(width: geo.size.width * 0.5)
                }

                formPane(showMobileBrand: !showHero)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .background(LoginTheme.background.ignoresSafeArea())
            }
        }
    }
}

private extension CrewLinkLoginView {
    var heroPane: some View {
        ZStack {
            AsyncImage(url: URL(string: "https://lh3.googleusercontent.com/aida-public/AB6AXuBad4Jj3SWvYqH0EuOG1QZm2ZVPcWV9d-AL07fSRPFdW0kXDvKCZhClxcFoMWAYut6UwLRpSXLIDruQa8BlL06rqdPf1sb7KFoCnQf4_j0EEWffTBXfBuMdaTeHtzGYK0-7-abG1EZRoxvqdk-LNLUMGgmsN1-OOfJNPrSIBaX6HcnfKe7q8KWxZTAbpkejWMS_mK_f3kIdvG7G7yH4GNAgNlW4-1I6Q1Pw_WYNl_8aevRzeMftlh_f7P5a0_7zgLNFU2Xy8tXgWAo")) { image in
                image.resizable().scaledToFill()
            } placeholder: {
                Color.black.opacity(0.2)
            }
            .overlay(LinearGradient(
                colors: [LoginTheme.background.opacity(0.95), LoginTheme.background.opacity(0.55), .clear],
                startPoint: .bottom,
                endPoint: .top
            ))
            .clipped()

            VStack(alignment: .leading, spacing: 20) {
                RoundedRectangle(cornerRadius: 12)
                    .fill(LoginTheme.primary.opacity(0.2))
                    .overlay(
                        Image(systemName: "airplane.departure")
                            .font(.system(size: 28, weight: .bold))
                            .foregroundStyle(LoginTheme.primary)
                    )
                    .frame(width: 48, height: 48)

                Text("Seamless Flight Operations.")
                    .font(.system(size: 48, weight: .bold))
                    .foregroundStyle(.white)
                    .lineLimit(2)

                Text("Access your rosters, check flight details, and manage your crew schedule securely from anywhere in the world.")
                    .font(.system(size: 20, weight: .medium))
                    .foregroundStyle(Color.white.opacity(0.8))
                    .frame(maxWidth: 520, alignment: .leading)

                HStack(spacing: 10) {
                    Circle().fill(.green).frame(width: 10, height: 10)
                    Text("System Operational")
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(Color.white.opacity(0.85))
                }
                .padding(.horizontal, 14)
                .padding(.vertical, 9)
                .background(Color.white.opacity(0.08))
                .clipShape(Capsule())
                .overlay(Capsule().stroke(Color.white.opacity(0.15), lineWidth: 1))
            }
            .padding(64)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomLeading)
        }
        .background(LoginTheme.background)
    }

    func formPane(showMobileBrand: Bool) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                if showMobileBrand {
                    HStack(spacing: 10) {
                        RoundedRectangle(cornerRadius: 10)
                            .fill(LoginTheme.primary)
                            .frame(width: 40, height: 40)
                            .overlay(Image(systemName: "airplane.departure").foregroundStyle(.white))
                        Text("Calendar.LAB")
                            .font(.system(size: 24, weight: .bold))
                            .foregroundStyle(LoginTheme.textPrimary)
                    }
                    .padding(.bottom, 8)
                }

                VStack(alignment: .leading, spacing: 8) {
                    Text("Welcome, You!")
                        .font(.system(size: 34, weight: .bold))
                        .foregroundStyle(LoginTheme.textPrimary)
                    Text("Please sign in to access your dashboard.")
                        .font(.system(size: 16))
                        .foregroundStyle(LoginTheme.textSecondary)
                }

                googleButton

                if let signedInEmail = googleSignIn.signedInEmail {
                    Text("Signed in as \(signedInEmail)")
                        .font(.system(size: 13, weight: .medium))
                        .foregroundStyle(Color.green)
                }
                if let errorMessage = googleSignIn.errorMessage {
                    Text(errorMessage)
                        .font(.system(size: 13, weight: .medium))
                        .foregroundStyle(Color.orange)
                }

                HStack {
                    Rectangle().fill(LoginTheme.border).frame(height: 1)
                    Text("Or continue with email")
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(LoginTheme.textSecondary)
                        .padding(.horizontal, 10)
                    Rectangle().fill(LoginTheme.border).frame(height: 1)
                }

                Group {
                    inputField(title: "Email address", icon: "envelope", text: $email, isSecure: false)
                    inputField(title: "Password", icon: "lock", text: $password, isSecure: true)
                }

                HStack {
                    Toggle("Remember me", isOn: $rememberMe)
                        .toggleStyle(.checkboxLike)
                        .font(.system(size: 14))
                        .foregroundStyle(LoginTheme.textSecondary)

                    Spacer()
                    Button("Forgot password?") {}
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundStyle(LoginTheme.primary)
                }

                Button {
                    authMessage = "Email login not wired in this mockup."
                } label: {
                    HStack(spacing: 8) {
                        Text("Log In")
                        Image(systemName: "arrow.right")
                    }
                    .font(.system(size: 15, weight: .bold))
                    .foregroundStyle(.white)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 13)
                    .background(LoginTheme.primary)
                    .clipShape(RoundedRectangle(cornerRadius: 12))
                }
                .buttonStyle(.plain)

                if let authMessage {
                    Text(authMessage)
                        .font(.system(size: 13, weight: .medium))
                        .foregroundStyle(Color.orange)
                }

                VStack(spacing: 12) {
                    HStack(spacing: 4) {
                        Text("Having technical issues?")
                            .foregroundStyle(LoginTheme.textSecondary)
                        Button("Contact IT Support") {}
                            .font(.system(size: 14, weight: .bold))
                            .foregroundStyle(LoginTheme.primary)
                    }
                    .font(.system(size: 14))

                    Text("Unauthorized access is prohibited.\nProperty of Calendar.LAB Development Team")
                        .font(.system(size: 12))
                        .foregroundStyle(LoginTheme.textMuted)
                        .multilineTextAlignment(.center)
                }
                .frame(maxWidth: .infinity)
                .padding(.top, 6)
            }
            .padding(.horizontal, 28)
            .padding(.vertical, 36)
            .frame(maxWidth: 520)
            .frame(maxWidth: .infinity)
        }
        .scrollIndicators(.hidden)
    }

    var googleButton: some View {
        Button {
            googleSignIn.signIn()
        } label: {
            HStack(spacing: 10) {
                GoogleMark()
                    .frame(width: 20, height: 20)
                Text(googleSignIn.isLoading ? "Signing in..." : "Sign in with Google")
                    .font(.system(size: 16, weight: .bold))
            }
            .foregroundStyle(LoginTheme.textPrimary)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 13)
            .background(LoginTheme.surface)
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(LoginTheme.border, lineWidth: 1))
            .clipShape(RoundedRectangle(cornerRadius: 12))
        }
        .buttonStyle(.plain)
        .disabled(googleSignIn.isLoading)
    }

    func inputField(title: String, icon: String, text: Binding<String>, isSecure: Bool) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.system(size: 14, weight: .medium))
                .foregroundStyle(LoginTheme.textPrimary)

            HStack(spacing: 10) {
                Image(systemName: icon)
                    .foregroundStyle(LoginTheme.textSecondary)
                    .frame(width: 18)

                if isSecure {
                    SecureField(isSecure ? "••••••••" : "", text: text)
                        .textContentType(.password)
                } else {
                    TextField("captain@email-pessoal.com", text: text)
                        .textContentType(.emailAddress)
                        .keyboardType(.emailAddress)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                }
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 12)
            .background(LoginTheme.surface)
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(LoginTheme.border, lineWidth: 1))
            .clipShape(RoundedRectangle(cornerRadius: 12))
            .foregroundStyle(LoginTheme.textPrimary)
        }
    }

}

private struct GoogleMark: View {
    var body: some View {
        ZStack {
            Circle().trim(from: 0.0, to: 0.28).stroke(Color(red: 66/255, green: 133/255, blue: 244/255), style: .init(lineWidth: 4, lineCap: .round))
            Circle().trim(from: 0.28, to: 0.52).stroke(Color(red: 234/255, green: 67/255, blue: 53/255), style: .init(lineWidth: 4, lineCap: .round))
            Circle().trim(from: 0.52, to: 0.74).stroke(Color(red: 251/255, green: 188/255, blue: 5/255), style: .init(lineWidth: 4, lineCap: .round))
            Circle().trim(from: 0.74, to: 1.0).stroke(Color(red: 52/255, green: 168/255, blue: 83/255), style: .init(lineWidth: 4, lineCap: .round))
            Rectangle()
                .fill(Color(red: 66/255, green: 133/255, blue: 244/255))
                .frame(width: 8, height: 3)
                .offset(x: 4.5)
        }
        .rotationEffect(.degrees(-45))
    }
}

private enum LoginTheme {
    static let primary = Color(red: 19 / 255, green: 109 / 255, blue: 236 / 255)
    static let background = Color(red: 16 / 255, green: 24 / 255, blue: 34 / 255)
    static let surface = Color(red: 28 / 255, green: 38 / 255, blue: 51 / 255)
    static let border = Color(red: 55 / 255, green: 70 / 255, blue: 90 / 255)
    static let textPrimary = Color.white
    static let textSecondary = Color(red: 163 / 255, green: 176 / 255, blue: 194 / 255)
    static let textMuted = Color(red: 120 / 255, green: 136 / 255, blue: 156 / 255)
}

private struct CheckboxLikeToggleStyle: ToggleStyle {
    func makeBody(configuration: Configuration) -> some View {
        Button {
            configuration.isOn.toggle()
        } label: {
            HStack(spacing: 8) {
                RoundedRectangle(cornerRadius: 4)
                    .stroke(LoginTheme.border, lineWidth: 1)
                    .background(
                        RoundedRectangle(cornerRadius: 4)
                            .fill(configuration.isOn ? LoginTheme.primary : .clear)
                    )
                    .frame(width: 16, height: 16)
                    .overlay {
                        if configuration.isOn {
                            Image(systemName: "checkmark")
                                .font(.system(size: 10, weight: .bold))
                                .foregroundStyle(.white)
                        }
                    }
                configuration.label
            }
        }
        .buttonStyle(.plain)
    }
}

private extension ToggleStyle where Self == CheckboxLikeToggleStyle {
    static var checkboxLike: CheckboxLikeToggleStyle { .init() }
}

#Preview {
    CrewLinkLoginView()
        .preferredColorScheme(.dark)
}
