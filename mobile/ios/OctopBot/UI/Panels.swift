import SwiftUI
import UserNotifications

/// The current Bot's conversations: search, grouped by day, open one, start a new one, swipe to delete.
struct HistorySheet: View {
    @Environment(\.dismiss) private var dismiss
    let chat: ChatSession
    @State private var query = ""
    @State private var loaded = false

    private var groups: [(DateBucket, [ConversationSummary])] {
        let text = query.trimmingCharacters(in: .whitespaces)
        let shown = text.isEmpty ? chat.conversations : chat.conversations.filter { $0.title.localizedCaseInsensitiveContains(text) }
        let grouped = Dictionary(grouping: shown) { DateBucket.of($0.updatedAt) }
        return DateBucket.allCases.compactMap { bucket in grouped[bucket].map { (bucket, $0) } }
    }

    var body: some View {
        NavigationStack {
            List {
                if query.isEmpty {
                    Section {
                        Button {
                            chat.newChat()
                            dismiss()
                        } label: {
                            Label("chat.new", systemImage: "square.and.pencil").font(.headline)
                        }
                    }
                }
                ForEach(groups, id: \.0) { bucket, rows in
                    Section(bucket.title) {
                        ForEach(rows) { conversation in
                            row(conversation)
                        }
                    }
                }
                if groups.isEmpty {
                    Group {
                        if !loaded {
                            ProgressView().frame(maxWidth: .infinity)
                        } else {
                            Text(query.isEmpty ? "drawer.empty" : "history.noMatch")
                                .font(.subheadline).foregroundStyle(Palette.secondary)
                        }
                    }
                    .listRowBackground(Color.clear)
                }
            }
            .searchable(text: $query, placement: .navigationBarDrawer(displayMode: .always), prompt: Text("history.search"))
            .refreshable { await chat.reloadConversations() }
            .navigationTitle(chat.bot.name)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("common.done") { dismiss() } } }
            .task {
                await chat.reloadConversations()
                loaded = true
            }
        }
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
    }

    private func row(_ conversation: ConversationSummary) -> some View {
        Button {
            dismiss()
            Task { await chat.open(conversation) }
        } label: {
            HStack(spacing: 10) {
                VStack(alignment: .leading, spacing: 3) {
                    Text(conversation.title.isEmpty ? L("chat.untitled") : conversation.title)
                        .lineLimit(1)
                        .foregroundStyle(Palette.text)
                    if let date = conversation.updatedAt {
                        Text(date.relative).font(.caption).foregroundStyle(Palette.secondary)
                    }
                }
                Spacer(minLength: 0)
                if chat.conversationId == conversation.id {
                    Image(systemName: "checkmark").font(.footnote.weight(.semibold)).foregroundStyle(chat.bot.accent)
                }
            }
        }
        .swipeActions {
            Button("common.delete", systemImage: "trash", role: .destructive) { Task { await chat.delete(conversation) } }
        }
    }
}

/// Change a Bot's look (and, for phone-local Bots, its name and persona).
struct BotEditor: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State var bot: BotProfile
    var isNew = false
    @State private var saving = false
    @State private var error: String?
    @State private var confirmDelete = false

    /// Lynxce Bots live on the phone; on a server the persona is set once, at creation.
    private var editsPersona: Bool { model.isLynxce || isNew }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    VStack(spacing: 12) {
                        CharacterView(look: bot.look, size: 120, seed: bot.id)
                            .id(bot.look)
                            .transition(.scale(scale: 0.8).combined(with: .opacity))
                        Button {
                            Haptics.tap()
                            withAnimation(.snappy) { shuffle() }
                        } label: {
                            Label("bot.shuffle", systemImage: "shuffle")
                        }
                        .buttonStyle(PillButtonStyle())
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 8)
                    .listRowBackground(Color.clear)
                }
                if editsPersona {
                    Section("bot.name") {
                        TextField("bot.name.placeholder", text: $bot.name)
                    }
                    Section {
                        TextField("bot.persona.placeholder", text: Binding(get: { bot.systemPrompt ?? "" }, set: { bot.systemPrompt = $0 }), axis: .vertical)
                            .lineLimit(3...8)
                    } header: {
                        Text("bot.persona")
                    }
                }
                Section("bot.shape") {
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 52), spacing: 10)], spacing: 10) {
                        ForEach(shapes, id: \.self) { shape in
                            Button { withAnimation(.snappy) { bot.look.shape = shape } } label: {
                                CharacterView(look: Look(shape: shape, color: bot.look.color), size: 44, seed: shape)
                                    .padding(4)
                                    .background(bot.look.shape == shape ? Palette.raised : .clear, in: RoundedRectangle(cornerRadius: 12))
                            }
                            .buttonStyle(.plain)
                        }
                    }
                    .padding(.vertical, 6)
                }
                if !bot.look.isOctopus {
                    Section("bot.color") {
                        LazyVGrid(columns: [GridItem(.adaptive(minimum: 36), spacing: 10)], spacing: 10) {
                            ForEach(Characters.inkIds, id: \.self) { ink in
                                Button { withAnimation(.snappy) { bot.look.color = ink } } label: {
                                    Circle()
                                        .fill(ink == "aurora"
                                              ? AnyShapeStyle(LinearGradient(stops: Characters.library.aurora, startPoint: .topLeading, endPoint: .bottomTrailing))
                                              : AnyShapeStyle(Characters.ink(ink)))
                                        .frame(width: 32, height: 32)
                                        .overlay(Circle().stroke(Palette.secondary.opacity(0.45), lineWidth: 1))
                                        .overlay(Circle().stroke(Palette.text, lineWidth: bot.look.color == ink ? 2.5 : 0).padding(-4))
                                }
                                .buttonStyle(.plain)
                                .accessibilityLabel(Text(ink))
                            }
                        }
                        .padding(.vertical, 8)
                    }
                }
                if let error { Section { Text(error).foregroundStyle(.red) } }
                if bot.isLocal && !isNew {
                    Section {
                        Button("bot.delete", role: .destructive) { confirmDelete = true }
                            .frame(maxWidth: .infinity)
                    }
                }
            }
            .confirmationDialog(Text("bot.delete.confirm \(bot.name)"), isPresented: $confirmDelete, titleVisibility: .visible) {
                Button("bot.delete", role: .destructive) {
                    model.deleteLocalBot(bot)
                    dismiss()
                }
            }
            .navigationTitle(isNew ? "bot.new" : "bot.edit")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("common.cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    if saving { ProgressView() } else {
                        Button("common.save", action: save)
                            .disabled(editsPersona && bot.name.trimmingCharacters(in: .whitespaces).isEmpty)
                    }
                }
            }
        }
    }

    private var shapes: [String] { Characters.shapeIds.filter { $0 != "octop" || bot.isChief } }

    private func shuffle() {
        if !bot.look.isOctopus, let shape = shapes.filter({ $0 != bot.look.shape && $0 != "octop" }).randomElement() {
            bot.look.shape = shape
        }
        if let ink = Characters.inkIds.filter({ $0 != bot.look.color }).randomElement() { bot.look.color = ink }
    }

    private func save() {
        Haptics.tap()
        if isNew, model.server != nil {
            saving = true
            Task {
                defer { saving = false }
                do {
                    bot.name = bot.name.trimmingCharacters(in: .whitespaces)
                    try await model.createServerBot(bot)
                    dismiss()
                } catch {
                    self.error = error.localizedDescription
                }
            }
            return
        }
        if model.isLynxce {
            bot.name = bot.name.trimmingCharacters(in: .whitespaces)
            model.saveLocalBot(bot)
            dismiss()
            return
        }
        saving = true
        Task {
            defer { saving = false }
            do {
                try await model.setLook(bot.look, for: bot)
                dismiss()
            } catch {
                self.error = error.localizedDescription
            }
        }
    }
}

struct SettingsView: View {
    @Environment(AppModel.self) private var model
    @Environment(Preferences.self) private var preferences
    @Environment(\.dismiss) private var dismiss
    @Environment(\.scenePhase) private var scenePhase
    @State private var confirmSignOut = false
    @State private var confirmClear = false
    @State private var cleared = false
    @State private var copied = false
    @State private var notifications: UNAuthorizationStatus = .notDetermined

    private var version: String {
        let info = Bundle.main.infoDictionary ?? [:]
        let short = info["CFBundleShortVersionString"] as? String ?? "0"
        let build = info["CFBundleVersion"] as? String ?? "0"
        return "\(short) (\(build))"
    }

    var body: some View {
        @Bindable var model = model
        @Bindable var preferences = preferences
        NavigationStack {
            Form {
                Section { accountCard }

                Section("settings.general") {
                    Picker(selection: $preferences.language) {
                        Text("settings.language.system").tag(AppLanguage.system)
                        Text(verbatim: "简体中文").tag(AppLanguage.chinese)
                        Text(verbatim: "English").tag(AppLanguage.english)
                    } label: { row("settings.language", "globe", .blue) }
                    Picker(selection: $preferences.appearance) {
                        Text("settings.appearance.system").tag(AppAppearance.system)
                        Text("settings.appearance.dark").tag(AppAppearance.dark)
                        Text("settings.appearance.light").tag(AppAppearance.light)
                    } label: { row("settings.appearance", "circle.lefthalf.filled", .indigo) }
                    Picker(selection: $preferences.textSize) {
                        Text("settings.textSize.small").tag(TextSize.small)
                        Text("settings.textSize.standard").tag(TextSize.standard)
                        Text("settings.textSize.large").tag(TextSize.large)
                    } label: { row("settings.textSize", "textformat.size", .teal) }
                    Toggle(isOn: $preferences.haptics) { row("settings.haptics", "hand.tap", .pink) }
                }
                .onChange(of: preferences.language) {
                    // Built-in Bot names and personas are localized.
                    Task { await model.refresh() }
                }

                Section {
                    if model.isLynxce {
                        NavigationLink {
                            ModelPicker()
                        } label: {
                            LabeledContent {
                                Text(model.models.first { $0.id == model.selectedModel }?.name ?? L("settings.model.auto"))
                            } label: { row("settings.model", "cpu", .purple) }
                        }
                    }
                    Toggle(isOn: $preferences.expandThinking) { row("settings.expandThinking", "sparkles", .orange) }
                    Toggle(isOn: $model.readAloud) { row("settings.readAloud", "speaker.wave.2", .green) }
                    Picker(selection: $preferences.speechSpeed) {
                        Text("settings.speed.slow").tag(SpeechSpeed.slow)
                        Text("settings.speed.normal").tag(SpeechSpeed.normal)
                        Text("settings.speed.fast").tag(SpeechSpeed.fast)
                    } label: { row("settings.speed", "gauge.with.dots.needle.33percent", .mint) }
                } header: {
                    Text("settings.chat")
                } footer: {
                    if model.isLynxce { Text("settings.model.footer") }
                }

                Section {
                    Toggle(isOn: $model.notifyOnReply) { row("settings.notify", "bell.badge", .red) }
                        .disabled(notifications == .denied)
                } header: {
                    Text("settings.notifications")
                } footer: {
                    if notifications == .denied {
                        VStack(alignment: .leading, spacing: 6) {
                            Text("settings.notify.denied")
                            Button("settings.openSystem") {
                                if let url = URL(string: UIApplication.openSettingsURLString) { UIApplication.shared.open(url) }
                            }
                            .font(.footnote.weight(.semibold))
                        }
                    }
                }

                Section {
                    Button { confirmClear = true } label: {
                        LabeledContent {
                            if cleared { Text("settings.cleared").foregroundStyle(Palette.secondary) }
                        } label: { row("settings.clearCache", "trash", .gray) }
                    }
                    .foregroundStyle(Palette.text)
                } header: {
                    Text("settings.storage")
                } footer: {
                    Text("settings.clearCache.footer")
                }

                Section("settings.account") {
                    LabeledContent { Text(model.backend?.accountName ?? "") } label: {
                        row("settings.signedInAs", "person", .blue)
                    }
                    if let server = model.server {
                        Button {
                            UIPasteboard.general.string = server.session.baseURL.absoluteString
                            Haptics.success()
                            copied = true
                        } label: {
                            LabeledContent {
                                Text(copied ? L("common.copied") : server.session.baseURL.absoluteString)
                                    .lineLimit(1).truncationMode(.middle)
                                    .foregroundStyle(Palette.secondary)
                            } label: { row("settings.connection", "server.rack", .cyan) }
                        }
                        .foregroundStyle(Palette.text)
                    } else {
                        LabeledContent { Text("settings.lynxce") } label: { row("settings.connection", "cloud", .cyan) }
                    }
                    Button {
                        dismiss()
                        Task { await model.switchAccount() }
                    } label: { row("settings.switch", "arrow.left.arrow.right", .gray) }
                    .foregroundStyle(Palette.text)
                    .accessibilityIdentifier("switchAccount")
                }

                Section("settings.about") {
                    LabeledContent { Text(verbatim: version) } label: { row("settings.version", "info.circle", .gray) }
                    link("settings.github", "chevron.left.forwardslash.chevron.right", .gray, "https://github.com/alison-xx/octop-bot")
                    link("settings.feedback", "exclamationmark.bubble", .orange, "https://github.com/alison-xx/octop-bot/issues/new")
                    link("settings.lynxceSite", "globe.asia.australia", .blue, "https://www.lynxce.cn")
                }

                Section {
                    Button("settings.signOut", role: .destructive) { confirmSignOut = true }
                        .frame(maxWidth: .infinity)
                        .accessibilityIdentifier("signOut")
                }
            }
            .tint(Characters.ink("rose"))
            // The navigation bar caches its title; rebuild it when the language changes.
            .id(preferences.language)
            .navigationTitle("settings.title")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("common.done") { dismiss() } } }
            .confirmationDialog("settings.signOut.confirm", isPresented: $confirmSignOut, titleVisibility: .visible) {
                Button("settings.signOut", role: .destructive) {
                    dismiss()
                    Task { await model.signOut() }
                }
            }
            .confirmationDialog("settings.clearCache.confirm", isPresented: $confirmClear, titleVisibility: .visible) {
                Button("settings.clearCache", role: .destructive) {
                    model.clearCache()
                    Haptics.success()
                    withAnimation { cleared = true }
                }
            }
            .task { notifications = await Notifier.status() }
            .onChange(of: scenePhase) { _, phase in
                if phase == .active { Task { notifications = await Notifier.status() } }
            }
            .onChange(of: model.notifyOnReply) {
                Task {
                    try? await Task.sleep(for: .seconds(1))
                    notifications = await Notifier.status()
                }
            }
        }
    }

    private var accountCard: some View {
        HStack(spacing: 14) {
            CharacterView(look: .chief, size: 56)
            VStack(alignment: .leading, spacing: 4) {
                Text(model.backend?.accountName ?? "").font(.headline).lineLimit(1)
                HStack(spacing: 5) {
                    Image(systemName: model.isLynxce ? "cloud.fill" : "server.rack").font(.caption)
                    Text(model.isLynxce ? L("settings.lynxce") : (model.server?.host ?? "")).lineLimit(1)
                }
                .font(.subheadline)
                .foregroundStyle(Palette.secondary)
                if let balance = model.balance {
                    Text("settings.balance.chip \(balance)")
                        .font(.caption.weight(.semibold))
                        .padding(.horizontal, 10)
                        .padding(.vertical, 4)
                        .background(Characters.ink("rose").opacity(0.15), in: Capsule())
                        .foregroundStyle(Characters.ink("rose"))
                }
            }
            Spacer(minLength: 0)
        }
        .padding(.vertical, 6)
    }

    private func row(_ title: LocalizedStringKey, _ symbol: String, _ color: Color) -> some View {
        Label {
            Text(title)
        } icon: {
            SettingsIcon(symbol: symbol, color: color)
        }
    }

    private func link(_ title: LocalizedStringKey, _ symbol: String, _ color: Color, _ url: String) -> some View {
        Link(destination: URL(string: url)!) {
            HStack {
                row(title, symbol, color)
                Spacer()
                Image(systemName: "arrow.up.right").font(.footnote.weight(.semibold)).foregroundStyle(Palette.secondary)
            }
        }
        .foregroundStyle(Palette.text)
    }
}

/// A white symbol on a colored rounded square, like the system Settings app.
struct SettingsIcon: View {
    var symbol: String
    var color: Color

    var body: some View {
        Image(systemName: symbol)
            .font(.system(size: 14, weight: .semibold))
            .foregroundStyle(.white)
            .frame(width: 28, height: 28)
            .background(color.gradient, in: RoundedRectangle(cornerRadius: 7, style: .continuous))
    }
}

/// Lynxce models: "Auto" first, a checkmark on the current one.
private struct ModelPicker: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        List {
            Section {
                option(nil, L("settings.model.auto"), detail: L("settings.model.footer"))
            }
            Section {
                ForEach(model.models) { choice in
                    option(choice.id, choice.name, detail: choice.supportsImage ? L("settings.model.vision") : nil)
                }
            }
        }
        .navigationTitle("settings.model")
        .navigationBarTitleDisplayMode(.inline)
    }

    private func option(_ id: String?, _ name: String, detail: String?) -> some View {
        Button {
            Haptics.tap()
            model.selectedModel = id
        } label: {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(name).foregroundStyle(Palette.text)
                    if let detail { Text(detail).font(.caption).foregroundStyle(Palette.secondary) }
                }
                Spacer()
                if model.selectedModel == id {
                    Image(systemName: "checkmark").font(.body.weight(.semibold)).foregroundStyle(Characters.ink("rose"))
                }
            }
        }
    }
}
