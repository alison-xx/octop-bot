import SafariServices
import SwiftUI

/// A Bot's cloud computer on Octop Bot cloud: is it running, and pause it to stop paying.
struct CloudComputerSection: View {
    let server: ServerBackend
    let botId: String
    @State private var status: ServerBackend.ComputerStatus?
    @State private var busy = false
    @State private var failed = false
    @State private var screen: URL?

    var body: some View {
        Section {
            LabeledContent {
                if let status {
                    Text(status.label).foregroundStyle(status.state == .running ? .green : Palette.secondary)
                } else if failed {
                    Text("computer.unavailable").foregroundStyle(Palette.secondary)
                } else {
                    ProgressView()
                }
            } label: {
                Label("computer.title", systemImage: "desktopcomputer")
            }
            .accessibilityIdentifier("computerState")
            if let since = status?.runningSince, status?.state == .running {
                LabeledContent("computer.since") {
                    Text(since, style: .relative).monospacedDigit().foregroundStyle(Palette.secondary)
                }
            }
            if status != nil {
                Button {
                    Task { await openScreen() }
                } label: {
                    Label("computer.view", systemImage: "display")
                }
                .disabled(busy)
                .accessibilityIdentifier("computerView")
                Button {
                    Task { await takeover(!(status?.takeover ?? false)) }
                } label: {
                    Label(status?.takeover == true ? "computer.handBack" : "computer.takeOver",
                          systemImage: status?.takeover == true ? "hand.raised.slash" : "hand.raised")
                }
                .disabled(busy)
                .accessibilityIdentifier("computerTakeover")
            }
            if status?.state == .running, status?.takeover != true {
                Button {
                    Task { await pause() }
                } label: {
                    HStack {
                        Text("computer.pause")
                        Spacer()
                        if busy { ProgressView() }
                    }
                }
                .disabled(busy)
                .accessibilityIdentifier("computerPause")
            }
        } header: {
            Text("computer.header")
        } footer: {
            Text("computer.footer")
        }
        .task { await load() }
        .sheet(item: $screen) { url in
            SafariView(url: url).ignoresSafeArea()
        }
    }

    private func openScreen() async {
        busy = true
        defer { busy = false }
        if let url = try? await server.screenURL(botId, control: status?.takeover == true) {
            screen = url
        }
    }

    private func takeover(_ active: Bool) async {
        busy = true
        defer { busy = false }
        if let next = try? await server.setTakeover(botId, active: active) {
            Haptics.success()
            status = next
        }
    }

    private func load() async {
        do {
            status = try await server.computerStatus(botId)
            failed = false
        } catch {
            failed = true
        }
    }

    private func pause() async {
        busy = true
        defer { busy = false }
        if let paused = try? await server.pauseComputer(botId) {
            Haptics.success()
            status = paused
        }
    }
}

extension ServerBackend {
    struct ComputerStatus: Equatable {
        enum State: String { case none, running, paused }
        var state: State
        var runningSince: Date?
        var takeover = false

        var label: String {
            switch state {
            case .none: L("computer.state.none")
            case .running: L("computer.state.running")
            case .paused: L("computer.state.paused")
            }
        }

        static func parse(_ data: Any) throws -> ComputerStatus {
            guard let body = data as? [String: Any], let state = (body["state"] as? String).flatMap(State.init(rawValue:)) else {
                throw APIError(kind: .server, status: 502, message: nil)
            }
            let since = (body["running_since"] as? NSNumber).map { Date(timeIntervalSince1970: $0.doubleValue) }
            return ComputerStatus(state: state, runningSince: since, takeover: body["takeover"] as? Bool ?? false)
        }
    }

    private func computerPath(_ agentId: String) -> String {
        "/api/octop-bot/computers/" + (agentId.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? agentId)
    }

    func computerStatus(_ agentId: String) async throws -> ComputerStatus {
        try .parse(try await json(.get, computerPath(agentId)))
    }

    func pauseComputer(_ agentId: String) async throws -> ComputerStatus {
        try .parse(try await json(.post, computerPath(agentId) + "/pause"))
    }

    func setTakeover(_ agentId: String, active: Bool) async throws -> ComputerStatus {
        try .parse(try await json(.post, computerPath(agentId) + "/takeover", json: ["active": active]))
    }

    /// The server's screen page for this computer, with a one-time ticket.
    func screenURL(_ agentId: String, control: Bool) async throws -> URL {
        let body = try await json(.post, computerPath(agentId) + "/screen") as? [String: Any]
        guard let wsPath = body?["ws_path"] as? String, let ticket = URLComponents(string: wsPath)?
            .queryItems?.first(where: { $0.name == "ticket" })?.value
        else { throw APIError(kind: .server, status: 502, message: nil) }
        return Self.screenPage(base: session.baseURL, agentId: agentId, ticket: ticket, control: control)
    }

    nonisolated static func screenPage(base: URL, agentId: String, ticket: String, control: Bool) -> URL {
        var components = URLComponents(url: base.appending(path: "/octop-bot/screen/\(agentId)"), resolvingAgainstBaseURL: false)!
        components.queryItems = [URLQueryItem(name: "ticket", value: ticket), URLQueryItem(name: "control", value: control ? "1" : "0")]
        return components.url!
    }
}


extension URL: @retroactive Identifiable {
    public var id: String { absoluteString }
}

/// The server's screen page in an in-app browser (noVNC needs a real web view).
struct SafariView: UIViewControllerRepresentable {
    let url: URL

    func makeUIViewController(context: Context) -> SFSafariViewController {
        SFSafariViewController(url: url)
    }

    func updateUIViewController(_ controller: SFSafariViewController, context: Context) {}
}
