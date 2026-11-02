import Foundation
import Combine

/// Numeric semantic version ordering; 1.1 and 1.1.0 denote the same version.
struct ReleaseVersion: Comparable, Equatable {
    let components: [UInt64]
    let prerelease: [String]

    init?(_ text: String) {
        let value = text.trimmingCharacters(in: .whitespacesAndNewlines)
        let pattern = #"^[vV]?([0-9]+)(?:\.([0-9]+))?(?:\.([0-9]+))?(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"#
        guard let expression = try? NSRegularExpression(pattern: pattern),
              let match = expression.firstMatch(in: value, range: NSRange(value.startIndex..., in: value)) else { return nil }
        func capture(_ index: Int) -> String? {
            guard let range = Range(match.range(at: index), in: value) else { return nil }
            return String(value[range])
        }
        var numbers: [UInt64] = []
        for index in 1...3 {
            guard let number = UInt64(capture(index) ?? "0") else { return nil }
            numbers.append(number)
        }
        components = numbers
        prerelease = capture(4)?.split(separator: ".").map(String.init) ?? []
    }
    static func < (lhs: Self, rhs: Self) -> Bool {
        for (a,b) in zip(lhs.components,rhs.components) where a != b { return a < b }
        if lhs.prerelease.isEmpty || rhs.prerelease.isEmpty {
            return !lhs.prerelease.isEmpty && rhs.prerelease.isEmpty
        }
        for (a,b) in zip(lhs.prerelease,rhs.prerelease) where a != b {
            switch (UInt64(a),UInt64(b)) {
            case let (.some(x),.some(y)): return x < y
            case (.some,.none): return true
            case (.none,.some): return false
            case (.none,.none): return a < b
            }
        }
        return lhs.prerelease.count < rhs.prerelease.count
    }
}

struct GitHubRelease: Decodable, Sendable, Identifiable {
    struct Asset: Decodable, Sendable {
        let name: String
        let browserDownloadURL: String
        enum CodingKeys: String, CodingKey {
            case name
            case browserDownloadURL = "browser_download_url"
        }
    }
    let tagName: String
    let name: String?
    let body: String?
    let htmlURL: String
    let draft: Bool
    let prerelease: Bool
    let assets: [Asset]
    var id: String { tagName }
    var versionLabel: String { name?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty == false ? name! : tagName }
    var releaseNotes: String {
        let notes = body?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return notes.isEmpty ? "本次发布未附详细改进说明，可前往 GitHub 查看。" : notes
    }
    var validatedReleasePageURL: URL? { Self.officialURL(htmlURL, prefix: "/easonzhangbin/toMONO/releases/tag/") }
    var releasePageURL: URL { validatedReleasePageURL ?? URL(string: "https://github.com/easonzhangbin/toMONO/releases")! }
    var downloadURL: URL {
        let matching = assets.filter {
            let name = $0.name.lowercased()
            return name.hasSuffix("applesilicon.dmg")
        }
        for asset in matching {
            if let url = Self.officialURL(asset.browserDownloadURL, prefix: "/easonzhangbin/toMONO/releases/download/") { return url }
        }
        return releasePageURL
    }
    static func officialURL(_ string: String, prefix: String) -> URL? {
        guard let url = URL(string: string), let parts = URLComponents(url: url, resolvingAgainstBaseURL: false),
              parts.scheme?.lowercased() == "https", parts.host?.lowercased() == "github.com",
              parts.user == nil, parts.password == nil, parts.port == nil || parts.port == 443,
              parts.query == nil, parts.fragment == nil,
              parts.path.hasPrefix(prefix), parts.path.count > prefix.count,
              !parts.path.split(separator: "/").contains(".."), !parts.path.contains("\\") else { return nil }
        return url
    }
    enum CodingKeys: String, CodingKey {
        case tagName = "tag_name"
        case htmlURL = "html_url"
        case name,body,draft,prerelease,assets
    }
}

/// An optional, read-only GitHub release check. It never uploads photos or installs code.
@MainActor final class UpdateChecker: ObservableObject {
    static let endpoint = URL(string: "https://api.github.com/repos/easonzhangbin/toMONO/releases/latest")!
    @Published private(set) var availableRelease: GitHubRelease?
    @Published private(set) var isChecking = false
    @Published private(set) var message: String?
    private let currentVersion: String
    private let session: URLSession

    init(currentVersion: String = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "1.1.0", session: URLSession? = nil) {
        self.currentVersion = currentVersion
        if let session { self.session = session }
        else {
            let config = URLSessionConfiguration.ephemeral
            config.timeoutIntervalForRequest = 12
            config.timeoutIntervalForResource = 12
            config.waitsForConnectivity = false
            config.httpShouldSetCookies = false
            config.httpCookieStorage = nil
            config.urlCredentialStorage = nil
            self.session = URLSession(configuration: config)
        }
    }
    func dismiss() { availableRelease = nil }
    func clearMessage() { message = nil }

    func check(manual: Bool = false) async {
        guard !isChecking else { return }
        isChecking = true
        message = nil
        defer { isChecking = false }
        var request = URLRequest(url: Self.endpoint, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 12)
        request.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
        request.setValue("2022-11-28", forHTTPHeaderField: "X-GitHub-Api-Version")
        request.setValue("toMONO/\(currentVersion)", forHTTPHeaderField: "User-Agent")
        request.httpShouldHandleCookies = false
        do {
            let (bytes,response) = try await session.bytes(for: request)
            guard let response = response as? HTTPURLResponse,
                  response.url?.scheme == "https", response.url?.host == "api.github.com",
                  response.url?.path == Self.endpoint.path else { throw CheckError.invalidResponse }
            if response.statusCode == 404 {
                if manual { message = "GitHub 暂无可用的正式新版本。" }; return
            }
            guard response.statusCode == 200 else {
                if manual { message = response.statusCode == 403 || response.statusCode == 429 ? "GitHub 暂时限制了更新检查，请稍后重试。" : "暂时无法检查更新，请稍后重试。" }; return
            }
            let limit = 1_048_576
            guard response.expectedContentLength <= limit else { throw CheckError.oversizedResponse }
            var data = Data()
            for try await byte in bytes {
                guard data.count < limit else { throw CheckError.oversizedResponse }
                data.append(byte)
            }
            let release = try JSONDecoder().decode(GitHubRelease.self, from: data)
            guard let remote = ReleaseVersion(release.tagName), let installed = ReleaseVersion(currentVersion),
                  release.validatedReleasePageURL != nil else { throw CheckError.invalidResponse }
            guard !release.draft, !release.prerelease, remote.prerelease.isEmpty else {
                if manual { message = "暂无更新的正式版本；测试版不会自动提示。" }; return
            }
            if remote > installed {
                availableRelease = release
            } else if manual {
                message = "当前已是最新正式版本（\(currentVersion)）。"
            }
        } catch is CancellationError {
            if manual { message = "已取消更新检查。" }
        } catch {
            if manual { message = "暂时无法连接 GitHub 检查更新。你仍可正常使用软件，稍后再试。" }
        }
    }
    private enum CheckError: Error { case invalidResponse, oversizedResponse }
}
