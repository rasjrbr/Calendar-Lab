import Foundation

struct GoogleAuthConfig {
    let clientID: String
    let serverClientID: String?

    static func loadFromBundle() -> GoogleAuthConfig? {
        let dict = Bundle.main.infoDictionary ?? [:]
        guard let clientID = dict["GOOGLE_CLIENT_ID"] as? String, !clientID.isEmpty else {
            return nil
        }
        let serverClientID = dict["GOOGLE_SERVER_CLIENT_ID"] as? String
        return GoogleAuthConfig(clientID: clientID, serverClientID: serverClientID)
    }
}
