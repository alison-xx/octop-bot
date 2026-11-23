import SwiftUI

/// A Bot's cloud computer on Octop Bot cloud: is it running, and pause it to stop paying.
struct CloudComputerSection: View {
    let server: ServerBackend
    let botId: String
    @State private var status: ServerBackend.ComputerStatus?
    @State private var busy = false
    @State private var failed = false

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
            if status?.state == .running {
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
            return ComputerStatus(state: state, runningSince: since)
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
}
