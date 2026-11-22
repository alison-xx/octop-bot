import SwiftUI

/// Home: the Bot directory, like a messenger full of characters.
struct HomeView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.scenePhase) private var scenePhase
    @State private var path = NavigationPath()
    @State private var showSettings = false
    @State private var editing: BotProfile?
    @State private var creating = false
    @State private var creatingGroup = false
    @State private var voiceBot: BotProfile?
    @State private var query = ""

    enum Route: Hashable {
        case bot(String)
        case group(GroupSummary)
    }

    var body: some View {
        NavigationStack(path: $path) {
            List {
                if let error = model.loadError, !model.bots.isEmpty {
                    Label(error, systemImage: "wifi.exclamationmark")
                        .font(.footnote)
                        .foregroundStyle(.orange)
                        .listRowBackground(Color.orange.opacity(0.12))
                        .onTapGesture { Task { await model.refresh() } }
                }
                Section {
                    ForEach(shownBots) { bot in
                        NavigationLink(value: Route.bot(bot.id)) { BotRow(bot: bot) }
                            .listRowBackground(Palette.background)
                            .listRowSeparatorTint(Palette.hairline)
                            .contextMenu { menu(for: bot) }
                            .swipeActions(edge: .trailing) {
                                if bot.isLocal {
                                    Button("common.delete", systemImage: "trash", role: .destructive) { model.deleteLocalBot(bot) }
                                }
                                if model.canEdit(bot) {
                                    Button("bot.edit", systemImage: "paintpalette") { editing = bot }.tint(bot.accent)
                                }
                            }
                            .swipeActions(edge: .leading) {
                                Button("voice.title", systemImage: "waveform") { voiceBot = bot }.tint(.indigo)
                            }
                            .accessibilityIdentifier("bot-\(bot.name)")
                    }
                    if shownBots.isEmpty && !query.isEmpty {
                        Text("home.noMatch").font(.subheadline).foregroundStyle(Palette.secondary)
                            .listRowBackground(Palette.background)
                    }
                } header: {
                    if !model.groups.isEmpty || model.server != nil { Text("home.bots") }
                }
                if model.server != nil && (query.isEmpty || !shownGroups.isEmpty) {
                    Section("groups.title") {
                        ForEach(shownGroups) { group in
                            NavigationLink(value: Route.group(group)) { GroupRow(group: group) }
                                .listRowBackground(Palette.background)
                                .listRowSeparatorTint(Palette.hairline)
                        }
                        if model.groups.isEmpty {
                            Text("groups.empty").font(.subheadline).foregroundStyle(Palette.secondary)
                                .listRowBackground(Palette.background)
                        }
                    }
                }
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
            .background(Palette.background.ignoresSafeArea())
            .refreshable { await model.refresh() }
            .searchable(text: $query, placement: .navigationBarDrawer(displayMode: .automatic), prompt: Text("home.search"))
            .overlay {
                if model.bots.isEmpty {
                    if model.isLoading {
                        ProgressView()
                    } else if let error = model.loadError {
                        ContentUnavailableView {
                            Label("home.offline", systemImage: "wifi.exclamationmark")
                        } description: {
                            Text(error)
                        } actions: {
                            Button("common.retry") { Task { await model.refresh() } }
                        }
                    }
                }
            }
            .overlay(alignment: .bottomTrailing) { voiceButton }
            .navigationTitle("Octop Bot")
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button { showSettings = true } label: { Image(systemName: "person.crop.circle") }
                        .accessibilityIdentifier("openSettings")
                }
                ToolbarItem(placement: .topBarTrailing) {
                    if model.server != nil {
                        Menu {
                            Button("bot.new", systemImage: "person.badge.plus") { creating = true }
                            Button("groups.new", systemImage: "person.3") { creatingGroup = true }
                        } label: { Image(systemName: "plus") }
                            .accessibilityIdentifier("newMenu")
                    } else {
                        Button { creating = true } label: { Image(systemName: "plus") }
                            .accessibilityLabel(Text("bot.new"))
                            .accessibilityIdentifier("newBot")
                    }
                }
            }
            .navigationDestination(for: Route.self) { route in
                switch route {
                case .bot(let id):
                    if let bot = model.bots.first(where: { $0.id == id }) {
                        ChatScreen(chat: model.session(for: bot))
                    }
                case .group(let group):
                    GroupRoomView(group: group)
                }
            }
        }
        .onChange(of: scenePhase) { _, phase in
            // Bots, looks and groups may have changed on the desktop while we were away.
            if phase == .active { Task { await model.refresh() } }
        }
        .sheet(isPresented: $showSettings) { SettingsView() }
        .sheet(item: $editing) { bot in BotEditor(bot: bot) }
        .sheet(isPresented: $creating) {
            BotEditor(
                bot: BotProfile(
                    id: "custom-" + UUID().uuidString.lowercased(), name: "", look: Look(shape: "gumdrop", color: "blue"),
                    isChief: false, systemPrompt: "", isLocal: true
                ),
                isNew: true
            )
        }
        .sheet(isPresented: $creatingGroup) { GroupCreator() }
        .fullScreenCover(item: $voiceBot) { bot in VoiceModeView(chat: model.session(for: bot)) }
    }

    private var shownBots: [BotProfile] {
        let text = query.trimmingCharacters(in: .whitespaces)
        guard !text.isEmpty else { return model.bots }
        return model.bots.filter { $0.name.localizedCaseInsensitiveContains(text) || ($0.subtitle ?? "").localizedCaseInsensitiveContains(text) }
    }

    private var shownGroups: [GroupSummary] {
        let text = query.trimmingCharacters(in: .whitespaces)
        guard !text.isEmpty else { return model.groups }
        return model.groups.filter { $0.name.localizedCaseInsensitiveContains(text) }
    }

    @ViewBuilder
    private func menu(for bot: BotProfile) -> some View {
        if model.canEdit(bot) {
            Button("bot.edit", systemImage: "paintpalette") { editing = bot }
        }
        Button("voice.title", systemImage: "waveform") { voiceBot = bot }
        if bot.isLocal {
            Button("common.delete", systemImage: "trash", role: .destructive) { model.deleteLocalBot(bot) }
        }
    }

    private var voiceButton: some View {
        Button { voiceBot = model.lastBot } label: {
            Image(systemName: "waveform")
                .font(.title2.weight(.semibold))
                .frame(width: 60, height: 60)
                .background(Palette.text, in: Circle())
                .foregroundStyle(Palette.background)
                .shadow(color: .black.opacity(0.25), radius: 12, y: 4)
        }
        .accessibilityLabel(Text("voice.title"))
        .padding(20)
        .disabled(model.bots.isEmpty)
    }
}

private struct BotRow: View {
    @Environment(AppModel.self) private var model
    let bot: BotProfile

    var body: some View {
        let motion = model.motion(of: bot)
        let preview = model.previews[bot.id]
        HStack(spacing: 14) {
            CharacterView(look: bot.look, size: 52, motion: motion, seed: bot.id)
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 6) {
                    Text(bot.name).font(.body.weight(.semibold)).foregroundStyle(Palette.text).lineLimit(1)
                    if bot.isChief {
                        Image(systemName: "star.fill").font(.caption2).foregroundStyle(.yellow)
                    }
                    Spacer(minLength: 4)
                    if let date = preview?.date {
                        Text(date.relative).font(.caption).foregroundStyle(Palette.secondary)
                    }
                }
                Group {
                    if motion != .idle {
                        Text(motion == .thinking ? "chat.thinking" : "chat.typing").foregroundStyle(bot.accent)
                    } else {
                        Text(preview?.text ?? bot.subtitle ?? "").foregroundStyle(Palette.secondary)
                    }
                }
                .font(.subheadline)
                .lineLimit(1)
            }
        }
        .padding(.vertical, 6)
    }
}

private struct GroupRow: View {
    let group: GroupSummary

    var body: some View {
        HStack(spacing: 14) {
            GroupCharacterView(members: group.members, size: 52)
            VStack(alignment: .leading, spacing: 3) {
                Text(group.name).font(.body.weight(.semibold)).foregroundStyle(Palette.text).lineLimit(1)
                Text(group.members.map(\.name).joined(separator: "、"))
                    .font(.subheadline).foregroundStyle(Palette.secondary).lineLimit(1)
            }
        }
        .padding(.vertical, 6)
    }
}

/// Pick a name and members for a new server group; Chief (or the first member) leads it.
private struct GroupCreator: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var picked: Set<String> = []
    @State private var saving = false
    @State private var error: String?

    var body: some View {
        NavigationStack {
            Form {
                Section("groups.name") {
                    TextField("groups.name.placeholder", text: $name)
                }
                Section("groups.members") {
                    ForEach(model.bots) { bot in
                        Button {
                            if picked.contains(bot.id) { picked.remove(bot.id) } else { picked.insert(bot.id) }
                        } label: {
                            HStack(spacing: 12) {
                                CharacterView(look: bot.look, size: 34, seed: bot.id)
                                Text(bot.name).foregroundStyle(Palette.text)
                                Spacer()
                                Image(systemName: picked.contains(bot.id) ? "checkmark.circle.fill" : "circle")
                                    .foregroundStyle(picked.contains(bot.id) ? bot.accent : Palette.secondary)
                                    .font(.title3)
                            }
                        }
                    }
                }
                if let error { Section { Text(error).foregroundStyle(.red) } }
            }
            .navigationTitle("groups.new")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("common.cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    if saving { ProgressView() } else {
                        Button("common.save", action: save)
                            .disabled(name.trimmingCharacters(in: .whitespaces).isEmpty || picked.count < 2)
                    }
                }
            }
        }
    }

    private func save() {
        saving = true
        Task {
            defer { saving = false }
            do {
                try await model.createGroup(
                    name: name.trimmingCharacters(in: .whitespaces),
                    members: model.bots.filter { picked.contains($0.id) }
                )
                dismiss()
            } catch {
                self.error = error.localizedDescription
            }
        }
    }
}
