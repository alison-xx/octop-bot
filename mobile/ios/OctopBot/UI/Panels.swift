import SwiftUI

/// The current Bot's conversations: open one, start a new one, swipe to delete.
struct HistorySheet: View {
    @Environment(\.dismiss) private var dismiss
    let chat: ChatSession

    var body: some View {
        NavigationStack {
            List {
                Section {
                    Button {
                        chat.newChat()
                        dismiss()
                    } label: {
                        Label("chat.new", systemImage: "square.and.pencil").font(.headline)
                    }
                }
                Section("drawer.recent") {
                    ForEach(chat.conversations) { conversation in
                        Button {
                            dismiss()
                            Task { await chat.open(conversation) }
                        } label: {
                            VStack(alignment: .leading, spacing: 3) {
                                Text(conversation.title.isEmpty ? L("chat.untitled") : conversation.title)
                                    .lineLimit(1)
                                    .foregroundStyle(Palette.text)
                                if let date = conversation.updatedAt {
                                    Text(date.relative).font(.caption).foregroundStyle(Palette.secondary)
                                }
                            }
                        }
                        .listRowBackground(chat.conversationId == conversation.id ? Palette.raised : Palette.surface)
                        .swipeActions {
                            Button("common.delete", role: .destructive) { Task { await chat.delete(conversation) } }
                        }
                    }
                    if chat.conversations.isEmpty {
                        Text("drawer.empty").font(.subheadline).foregroundStyle(Palette.secondary)
                    }
                }
            }
            .scrollContentBackground(.hidden)
            .background(Palette.background)
            .refreshable { await chat.reloadConversations() }
            .navigationTitle(chat.bot.name)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("common.done") { dismiss() } } }
            .task { await chat.reloadConversations() }
        }
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
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

    /// Lynxce Bots live on the phone; on a server the persona is set once, at creation.
    private var editsPersona: Bool { model.isLynxce || isNew }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    HStack {
                        Spacer()
                        CharacterView(look: bot.look, size: 120, seed: bot.id)
                        Spacer()
                    }
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
                        ForEach(Characters.shapeIds.filter { $0 != "octop" || bot.isChief }, id: \.self) { shape in
                            Button { bot.look.shape = shape } label: {
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
                                Button { bot.look.color = ink } label: {
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

    private func save() {
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
    @State private var confirmSignOut = false

    var body: some View {
        @Bindable var model = model
        @Bindable var preferences = preferences
        NavigationStack {
            Form {
                Section("settings.general") {
                    Picker("settings.language", selection: $preferences.language) {
                        Text("settings.language.system").tag(AppLanguage.system)
                        Text(verbatim: "简体中文").tag(AppLanguage.chinese)
                        Text(verbatim: "English").tag(AppLanguage.english)
                    }
                    Picker("settings.appearance", selection: $preferences.appearance) {
                        Text("settings.appearance.system").tag(AppAppearance.system)
                        Text("settings.appearance.dark").tag(AppAppearance.dark)
                        Text("settings.appearance.light").tag(AppAppearance.light)
                    }
                }
                .onChange(of: preferences.language) {
                    // Built-in Bot names and personas are localized.
                    Task { await model.refresh() }
                }
                Section("settings.account") {
                    LabeledContent("settings.signedInAs", value: model.backend?.accountName ?? "")
                    LabeledContent("settings.connection") {
                        Text(model.isLynxce ? L("settings.lynxce") : (model.server?.host ?? ""))
                    }
                    if let balance = model.balance {
                        LabeledContent("settings.balance", value: balance)
                    }
                }
                if model.isLynxce {
                    Section {
                        Picker("settings.model", selection: $model.selectedModel) {
                            Text("settings.model.auto").tag(String?.none)
                            ForEach(model.models) { option in Text(option.name).tag(Optional(option.id)) }
                        }
                    } footer: {
                        Text("settings.model.footer")
                    }
                }
                Section("settings.voice") {
                    Toggle("settings.readAloud", isOn: $model.readAloud)
                    Toggle("settings.notify", isOn: $model.notifyOnReply)
                }
                Section("settings.about") {
                    LabeledContent("settings.version", value: Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "")
                    Link("settings.github", destination: URL(string: "https://github.com/alison-xx/octop-bot")!)
                }
                Section {
                    Button("settings.signOut", role: .destructive) { confirmSignOut = true }
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
        }
    }
}
