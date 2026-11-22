import Observation
import SwiftUI

/// A server Bot group's timeline, polled like the dashboard (2.5 s while active, 10 s idle).
@Observable
final class GroupRoom {
    let group: GroupSummary
    let server: ServerBackend
    var messages: [ServerBackend.GroupMessage] = []
    var drafts: [String: String] = [:]
    var goal: (title: String, status: String)?
    var error: String?
    var sending = false
    private var quietPolls = 0
    private var poller: Task<Void, Never>?

    init(group: GroupSummary, server: ServerBackend) {
        self.group = group
        self.server = server
    }

    func member(_ id: String?) -> BotProfile? { group.members.first { $0.id == id } }

    func start() {
        poller?.cancel()
        poller = Task {
            while !Task.isCancelled {
                await poll()
                let active = !drafts.isEmpty || sending || quietPolls < 4
                try? await Task.sleep(for: .seconds(active ? 2.5 : 10))
            }
        }
    }

    func stop() { poller?.cancel() }

    func poll() async {
        do {
            async let fresh = server.groupMessages(group.id, after: messages.last?.id)
            async let live = server.groupDrafts(group.id)
            let (new, current) = try await (fresh, live)
            if !new.isEmpty { messages += new.filter { row in !messages.contains { $0.id == row.id } } }
            drafts = Dictionary(current.map { ($0.agentId, $0.text) }, uniquingKeysWith: { _, b in b })
            quietPolls = new.isEmpty && current.isEmpty ? quietPolls + 1 : 0
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
        if goal == nil { goal = try? await server.groupGoal(group.id) }
    }

    func send(_ text: String) {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        let mentions = Self.mentions(in: trimmed, members: group.members)
        let requestId = UUID().uuidString.lowercased()
        messages.append(.init(id: "local-" + requestId, role: "user", agentId: nil, text: trimmed, createdAt: .now, requestId: requestId))
        sending = true
        quietPolls = 0
        start()
        Task {
            defer { sending = false }
            do {
                try await server.postGroupMessage(group.id, text: trimmed, mentions: mentions, requestId: requestId)
            } catch {
                self.error = error.localizedDescription
            }
            messages.removeAll { $0.id == "local-" + requestId }
            await poll()
        }
    }

    /// `@Name` handles in the text → member ids, longest names first so "@Ann Lee" beats "@Ann".
    static func mentions(in text: String, members: [BotProfile]) -> [String] {
        let unquoted = text.split(separator: "\n", omittingEmptySubsequences: false)
            .filter { !$0.trimmingCharacters(in: .whitespaces).hasPrefix(">") }
            .joined(separator: "\n")
        var remaining = unquoted
        var ids: [String] = []
        for member in members.sorted(by: { $0.name.count > $1.name.count }) {
            for handle in ["@" + member.name, "@" + member.id] where remaining.contains(handle) {
                if !ids.contains(member.id) { ids.append(member.id) }
                remaining = remaining.replacingOccurrences(of: handle, with: " ")
            }
        }
        return ids
    }
}

struct GroupRoomView: View {
    @Environment(AppModel.self) private var model
    let group: GroupSummary
    @State private var room: GroupRoom?
    @State private var text = ""
    @State private var showInfo = false

    var body: some View {
        VStack(spacing: 0) {
            if let room {
                timeline(room)
                composer(room)
            } else {
                ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .background(Palette.background)
        .navigationTitle(group.name)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button { showInfo = true } label: { GroupCharacterView(members: group.members, size: 30) }
            }
        }
        .sheet(isPresented: $showInfo) { if let room { GroupInfoView(room: room) } }
        .task {
            guard let server = model.server else { return }
            let room = GroupRoom(group: group, server: server)
            self.room = room
            room.start()
        }
        .onDisappear { room?.stop() }
    }

    private func timeline(_ room: GroupRoom) -> some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 16) {
                    if room.messages.isEmpty && room.drafts.isEmpty {
                        VStack(spacing: 12) {
                            HStack(spacing: -10) {
                                ForEach(room.group.members.prefix(5)) { bot in
                                    CharacterView(look: bot.look, size: 64, seed: bot.id)
                                }
                            }
                            Text("groups.start").font(.subheadline).foregroundStyle(Palette.secondary)
                                .multilineTextAlignment(.center)
                        }
                        .frame(maxWidth: .infinity)
                        .padding(.top, 120)
                    }
                    if let goal = room.goal {
                        Label(goal.title, systemImage: "flag.checkered")
                            .font(.subheadline.weight(.medium))
                            .padding(12)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(Palette.surface, in: RoundedRectangle(cornerRadius: 14))
                    }
                    ForEach(room.messages, id: \.id) { message in
                        row(message, room: room)
                    }
                    ForEach(room.drafts.sorted(by: { $0.key < $1.key }), id: \.key) { agent, draft in
                        botRow(room.member(agent), text: draft, live: true)
                    }
                    Color.clear.frame(height: 4).id("end")
                }
                .padding(16)
            }
            .defaultScrollAnchor(.bottom)
            .onChange(of: room.messages.count) { withAnimation { proxy.scrollTo("end") } }
            .onChange(of: room.drafts) { proxy.scrollTo("end") }
            .overlay(alignment: .top) {
                if let error = room.error {
                    Text(error).font(.footnote).padding(8).background(.red.opacity(0.15), in: Capsule()).padding(8)
                }
            }
        }
    }

    @ViewBuilder
    private func row(_ message: ServerBackend.GroupMessage, room: GroupRoom) -> some View {
        if message.role == "user" {
            HStack {
                Spacer(minLength: 48)
                Text(message.text)
                    .padding(.horizontal, 16).padding(.vertical, 11)
                    .background(Palette.surface, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
            }
        } else if message.role == "error" {
            Label(message.text, systemImage: "exclamationmark.triangle").font(.footnote).foregroundStyle(.red)
        } else {
            botRow(room.member(message.agentId), text: message.text, live: false)
        }
    }

    private func botRow(_ bot: BotProfile?, text: String, live: Bool) -> some View {
        HStack(alignment: .top, spacing: 10) {
            CharacterView(look: bot?.look ?? .fallback, size: 30, motion: live ? .working : .idle, seed: bot?.id ?? "")
            VStack(alignment: .leading, spacing: 4) {
                Text(bot?.name ?? "Bot").font(.caption.weight(.semibold)).foregroundStyle(bot?.accent ?? Palette.secondary)
                if text.isEmpty && live {
                    TypingDots()
                } else {
                    MarkdownText(text: text)
                }
            }
        }
    }

    private func composer(_ room: GroupRoom) -> some View {
        let query = Self.mentionQuery(text)
        let suggestions = query.map { q in room.group.members.filter { q.isEmpty || $0.name.localizedCaseInsensitiveContains(q) } } ?? []
        return VStack(spacing: 6) {
            if !suggestions.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        ForEach(suggestions) { bot in
                            Button {
                                if let at = text.lastIndex(of: "@") { text = String(text[..<at]) }
                                text += "@\(bot.name) "
                            } label: {
                                HStack(spacing: 6) {
                                    CharacterView(look: bot.look, size: 20, seed: bot.id)
                                    Text(bot.name)
                                }
                            }
                            .buttonStyle(PillButtonStyle())
                        }
                    }
                    .padding(.horizontal, 16)
                }
            }
            HStack(alignment: .bottom, spacing: 6) {
                TextField("groups.placeholder", text: $text, axis: .vertical)
                    .lineLimit(1...6)
                    .padding(.vertical, 10)
                    .padding(.leading, 14)
                Button {
                    room.send(text)
                    text = ""
                } label: {
                    Image(systemName: "arrow.up").font(.callout.weight(.bold)).frame(width: 36, height: 36)
                        .background(Palette.text, in: Circle()).foregroundStyle(Palette.background)
                }
                .disabled(text.trimmingCharacters(in: .whitespaces).isEmpty)
                .padding(.bottom, 2)
            }
            .padding(.trailing, 5)
            .padding(.vertical, 4)
            .background(Palette.surface, in: RoundedRectangle(cornerRadius: 26, style: .continuous))
            .padding(.horizontal, 12)
            .padding(.bottom, 8)
        }
    }

    /// The partial name after a trailing "@", if the user is typing a mention.
    static func mentionQuery(_ text: String) -> String? {
        guard let at = text.lastIndex(of: "@") else { return nil }
        let tail = text[text.index(after: at)...]
        guard !tail.contains(" "), !tail.contains("\n") else { return nil }
        if at > text.startIndex, !text[text.index(before: at)].isWhitespace { return nil }
        return String(tail)
    }
}

private struct GroupInfoView: View {
    let room: GroupRoom
    @Environment(\.dismiss) private var dismiss
    @State private var memory: String?

    var body: some View {
        NavigationStack {
            List {
                Section("groups.members") {
                    ForEach(room.group.members) { bot in
                        HStack(spacing: 12) {
                            CharacterView(look: bot.look, size: 32, seed: bot.id)
                            Text(bot.name)
                        }
                    }
                }
                if let goal = room.goal {
                    Section("groups.goal") {
                        Text(goal.title)
                        Text(goal.status).foregroundStyle(Palette.secondary)
                    }
                }
                Section("groups.memory") {
                    if let memory {
                        Text(memory.isEmpty ? L("groups.memory.empty") : memory)
                            .font(.callout)
                            .foregroundStyle(memory.isEmpty ? Palette.secondary : Palette.text)
                    } else {
                        ProgressView()
                    }
                }
            }
            .navigationTitle(room.group.name)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("common.done") { dismiss() } } }
            .task { memory = (try? await room.server.groupMemory(room.group.id)) ?? "" }
        }
        .presentationDetents([.medium, .large])
    }
}
