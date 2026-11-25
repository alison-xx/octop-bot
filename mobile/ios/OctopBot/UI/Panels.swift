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
    private var editsPersona: Bool { model.usesPhoneBots || isNew }

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
                if !isNew, let server = model.server {
                    Section {
                        NavigationLink {
                            BotActivityView(server: server, bot: bot)
                        } label: {
                            Label("profile.entry", systemImage: "clock.arrow.circlepath")
                        }
                        .accessibilityIdentifier("botActivity")
                    }
                }
                if !isNew, let server = model.server, server.isCloud {
                    CloudComputerSection(server: server, botId: bot.id)
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
        if model.usesPhoneBots {
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
    @State private var confirmDelete = false
    @State private var deleting = false
    @State private var deleteError: String?
    @State private var confirmClear = false
    @State private var cleared = false
    @State private var copied = false
    @State private var notifications: UNAuthorizationStatus = .notDetermined
    @State private var stars = GitHubStars.shared
    @State private var showCredits = false

    /// Design screenshots only (`-demoAccount YES`); release builds never show the sample card.
    private static var demoAccount: Bool {
        #if DEBUG
        UserDefaults.standard.bool(forKey: "demoAccount")
        #else
        false
        #endif
    }

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
                if model.creditAccount != nil || Self.demoAccount {
                    Section {
                        AccountCard(summary: model.accountSummary) { showCredits = true }
                            .listRowInsets(EdgeInsets())
                            .listRowBackground(Color.clear)
                    }
                } else {
                    Section { accountCard }
                }

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
                        .tint(.green)
                }
                .onChange(of: preferences.language) {
                    // Built-in Bot names and personas are localized.
                    Task { await model.refresh() }
                }

                Section {
                    if model.backend != nil {
                        NavigationLink {
                            ModelSourcesView()
                        } label: {
                            LabeledContent {
                                Text(model.currentModel?.model ?? L("models.none"))
                                    .lineLimit(1)
                            } label: { row("settings.model", "cpu", .purple) }
                        }
                        .accessibilityIdentifier("models")
                    }
                    Toggle(isOn: $preferences.expandThinking) { row("settings.expandThinking", "sparkles", .orange) }
                        .tint(.green)
                    Toggle(isOn: $model.readAloud) { row("settings.readAloud", "speaker.wave.2", .green) }
                        .tint(.green)
                    Picker(selection: $preferences.speechSpeed) {
                        Text("settings.speed.slow").tag(SpeechSpeed.slow)
                        Text("settings.speed.normal").tag(SpeechSpeed.normal)
                        Text("settings.speed.fast").tag(SpeechSpeed.fast)
                    } label: { row("settings.speed", "gauge.with.dots.needle.33percent", .mint) }
                } header: {
                    Text("settings.chat")
                } footer: {
                    Text(LocalizedStringKey(model.server.map { !$0.isCloud } == true ? "models.footerServer" : "models.footer"))
                }

                DeviceConnectorsSection()

                Section {
                    Toggle(isOn: $model.notifyOnReply) { row("settings.notify", "bell.badge", .red) }
                        .tint(.green)
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
                            .tint(.blue)
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
                    LabeledContent { Text(model.accountName) } label: {
                        row("settings.signedInAs", "person", .blue)
                    }
                    if model.creditAccount != nil {
                        NavigationLink {
                            CreditsView()
                        } label: {
                            LabeledContent {
                                BalanceLabel(allowsRetry: false)
                            } label: { row(CreditPurchases.title, "creditcard", .orange) }
                        }
                        .accessibilityIdentifier("credits")
                    } else if model.server != nil {
                        // A self-hosted server has no wallet here: usage only, and a note that nothing is billed.
                        NavigationLink {
                            CreditsView()
                        } label: { row("usage.title", "chart.bar", .orange) }
                        .accessibilityIdentifier("usage")
                    }
                    if model.isCloud {
                        LabeledContent { Text("settings.lynxce") } label: { row("settings.connection", "cloud", .cyan) }
                    } else if let server = model.server {
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
                    } else if model.isDevice {
                        LabeledContent { Text("account.connection.device") } label: { row("settings.connection", "iphone", .cyan) }
                    } else {
                        LabeledContent { Text("account.connection.lynxce") } label: { row("settings.connection", "cloud", .cyan) }
                    }
                    Button {
                        dismiss()
                        Task { await model.switchAccount() }
                    } label: { row("settings.switch", "arrow.left.arrow.right", .gray) }
                    .foregroundStyle(Palette.text)
                    .accessibilityIdentifier("switchAccount")
                }

                Section("settings.about") {
                    LabeledContent {
                        VStack(alignment: .trailing, spacing: 2) {
                            Text(verbatim: version)
                            updateStatus
                        }
                    } label: { row("settings.version", "info.circle", .gray) }
                    Button { AppUpdater.shared.check() } label: {
                        LabeledContent {
                            if AppUpdater.shared.status == .checking { ProgressView() }
                        } label: { row("update.check", "arrow.triangle.2.circlepath", .blue) }
                    }
                    .foregroundStyle(Palette.text)
                    .disabled(AppUpdater.shared.status == .checking)
                    Toggle(isOn: Bindable(AppUpdater.shared).receiveBeta) { row("update.beta", "testtube.2", .purple) }
                        .tint(.green)
                    repoLink(GitHubStars.bot)
                    repoLink(GitHubStars.octop)
                    link("settings.feedback", "exclamationmark.bubble", .orange, "https://github.com/alison-xx/octop-bot/issues/new")
                    link("settings.lynxceSite", "globe.asia.australia", .blue, "https://www.lynxce.cn")
                }

                Section {
                    if model.isDevice {
                        // Phone-only use has no account to leave; the keys and chats stay for next time.
                        Button("models.lynxce.signIn") {
                            dismiss()
                            Task { await model.signOut() }
                        }
                        .frame(maxWidth: .infinity)
                        .accessibilityIdentifier("signInLynxce")
                    } else {
                        Button("settings.signOut", role: .destructive) { confirmSignOut = true }
                            .frame(maxWidth: .infinity)
                            .accessibilityIdentifier("signOut")
                    }
                }

                if model.creditAccount != nil {
                    Section {
                        Button(role: .destructive) { confirmDelete = true } label: {
                            HStack {
                                Spacer()
                                if deleting { ProgressView() } else { Text("settings.deleteAccount") }
                                Spacer()
                            }
                        }
                        .disabled(deleting)
                        .accessibilityIdentifier("deleteAccount")
                    } footer: {
                        if let deleteError {
                            Text(deleteError).foregroundStyle(.red)
                        } else {
                            Text("settings.deleteAccount.footer")
                        }
                    }
                }
            }
            // Chosen values read as quiet grey; switches use the system green.
            .tint(Palette.secondary)
            // The navigation bar caches its title; rebuild it when the language changes.
            .id(preferences.language)
            .navigationTitle("settings.title")
            .navigationDestination(isPresented: $showCredits) { CreditsView() }
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("common.done") { dismiss() } } }
            .confirmationDialog("settings.signOut.confirm", isPresented: $confirmSignOut, titleVisibility: .visible) {
                Button("settings.signOut", role: .destructive) {
                    dismiss()
                    Task { await model.signOut() }
                }
            }
            .alert("settings.deleteAccount.confirm", isPresented: $confirmDelete) {
                Button("settings.deleteAccount", role: .destructive) { deleteAccount() }
                Button("common.cancel", role: .cancel) {}
            } message: {
                Text("settings.deleteAccount.message")
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

    private func deleteAccount() {
        deleting = true
        deleteError = nil
        Task {
            do {
                try await model.deleteAccount()
                dismiss()
            } catch {
                deleteError = error.localizedDescription
            }
            deleting = false
        }
    }

    /// One line under the version: current, available (tap to open the store), or failed.
    @ViewBuilder
    private var updateStatus: some View {
        switch AppUpdater.shared.status {
        case .upToDate:
            Text("update.upToDate").font(.caption).foregroundStyle(Palette.secondary)
        case .available(let latest, let url, let urgent):
            Link(destination: url) {
                Text(urgent ? L("update.urgent %@", latest) : L("update.available %@", latest))
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(urgent ? .orange : .blue)
                    .multilineTextAlignment(.trailing)
            }
        case .failed:
            Text("update.failed").font(.caption).foregroundStyle(.orange)
        case .checking:
            Text("update.checking").font(.caption).foregroundStyle(Palette.secondary)
        case .idle:
            EmptyView()
        }
    }

    private var accountCard: some View {
        HStack(spacing: 14) {
            LynxceAvatar(name: model.accountName, url: model.accountPhotoURL, localImage: model.localAccountImage, size: 56, branded: false)
            VStack(alignment: .leading, spacing: 4) {
                Text(model.accountName).font(.headline).lineLimit(1)
                HStack(spacing: 5) {
                    Image(systemName: model.modeSymbol).font(.caption)
                    Text(model.modeLabel).lineLimit(1)
                }
                .font(.subheadline)
                .foregroundStyle(Palette.secondary)
                if model.balance != nil {
                    BalanceLabel()
                        .font(.caption.weight(.semibold))
                        .padding(.horizontal, 10)
                        .padding(.vertical, 4)
                        .background(Palette.raised, in: Capsule())
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

    /// A GitHub project with its star count, like the website's header.
    private func repoLink(_ repo: GitHubStars.Repo) -> some View {
        Link(destination: repo.url) {
            HStack(spacing: 12) {
                Label {
                    VStack(alignment: .leading, spacing: 1) {
                        Text(verbatim: repo.name).foregroundStyle(Palette.text)
                        Text(verbatim: repo.path).font(.caption).foregroundStyle(Palette.secondary)
                    }
                } icon: {
                    SettingsIcon(symbol: "chevron.left.forwardslash.chevron.right", color: Color(white: 0.2))
                }
                Spacer()
                HStack(spacing: 3) {
                    Image(systemName: "star.fill").font(.caption2)
                    Text(verbatim: GitHubStars.format(stars.count(repo))).monospacedDigit()
                }
                .font(.footnote.weight(.semibold))
                .foregroundStyle(Palette.text)
                .padding(.horizontal, 8)
                .padding(.vertical, 3)
                .background(Palette.raised, in: Capsule())
                Image(systemName: "arrow.up.right").font(.footnote.weight(.semibold)).foregroundStyle(Palette.secondary)
            }
        }
        .accessibilityLabel(Text(verbatim: "\(repo.name), \(repo.path), \(GitHubStars.format(stars.count(repo))) stars"))
        .task { await stars.refresh(repo) }
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

/// GitHub star counts for the About section, cached like the website: the last
/// number shows at once, a fresh one is fetched at most every 6 hours, and a
/// built-in number covers the first launch and offline use.
@Observable
final class GitHubStars {
    struct Repo {
        var name: String
        var path: String
        var fallback: Int
        var url: URL { URL(string: "https://github.com/\(path)")! }
    }

    static let bot = Repo(name: "Octop Bot", path: "alison-xx/octop-bot", fallback: 6)
    static let octop = Repo(name: "Octop", path: "TencentCloud/Octop", fallback: 12_400)
    static let shared = GitHubStars()
    private static let maxAge: TimeInterval = 6 * 3600

    private var counts: [String: Int] = [:]

    func count(_ repo: Repo) -> Int {
        counts[repo.path] ?? cached(repo)?.count ?? repo.fallback
    }

    /// `1234` → "1.23k", `12400` → "12.4k", like the website.
    static func format(_ n: Int) -> String {
        guard n >= 1000 else { return String(n) }
        var text = String(format: n >= 10_000 ? "%.1f" : "%.2f", Double(n) / 1000)
        while text.hasSuffix("0") { text.removeLast() }
        if text.hasSuffix(".") { text.removeLast() }
        return text + "k"
    }

    private func key(_ repo: Repo) -> String { "github.stars.\(repo.path)" }

    private func cached(_ repo: Repo) -> (count: Int, at: Date)? {
        guard let entry = UserDefaults.standard.dictionary(forKey: key(repo)),
              let count = entry["n"] as? Int, let at = entry["at"] as? Double else { return nil }
        return (count, Date(timeIntervalSince1970: at))
    }

    func refresh(_ repo: Repo) async {
        if let cached = cached(repo), Date().timeIntervalSince(cached.at) < Self.maxAge { return }
        var request = URLRequest(url: URL(string: "https://api.github.com/repos/\(repo.path)")!, timeoutInterval: 5)
        request.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
        guard let (data, response) = try? await URLSession.shared.data(for: request),
              (response as? HTTPURLResponse)?.statusCode == 200,
              let body = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let count = body["stargazers_count"] as? Int else { return }
        counts[repo.path] = count
        UserDefaults.standard.set(["n": count, "at": Date().timeIntervalSince1970], forKey: key(repo))
    }
}


/// What the account card shows. Only the name is always known; the rest arrives with Lynxce's member
/// profile (avatar, tier, masked id, renewal date, and the balance split into expiring and permanent
/// credits) and is left out until then.
struct AccountSummary: Equatable {
    var name: String
    var avatarURL: URL?
    var localImage: Data?
    var tier: String?
    /// Masked Lynxce id, e.g. "138****0000".
    var accountHint: String?
    var memberUntil: Date?
    var credits: Double?
    var expiring: Double?
    var expiringOn: Date?
    var signupExpiryDay: String? = nil
    var permanent: Double?

    /// Sample data for design screenshots (`-demoAccount YES`, debug builds only).
    static let demo = AccountSummary(
        name: "Octo", tier: L("account.demoTier"), accountHint: "138****0000",
        memberUntil: Calendar.current.date(from: DateComponents(year: 2026, month: 12, day: 31)),
        credits: 4_440_164, expiring: 2_300,
        expiringOn: Calendar.current.date(from: DateComponents(year: 2026, month: 11, day: 30)),
        permanent: 4_437_864
    )
}

/// The Lynxce account at the top of Settings, like the desktop's card-style account menu: avatar with
/// the Lynxce mark, tier, masked id and renewal date, then the balance with what expires and what stays.
/// iOS has no 个人中心 entry and never points to the website (App Store 3.1.1); the card opens 积分 in the app.
struct AccountCard: View {
    let summary: AccountSummary
    var openCredits: (() -> Void)?

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 12) {
                LynxceAvatar(name: summary.name, url: summary.avatarURL, localImage: summary.localImage, size: 52)
                VStack(alignment: .leading, spacing: 4) {
                    HStack(spacing: 8) {
                        Text(verbatim: summary.name).font(.headline).lineLimit(1)
                        if let tier = summary.tier { TierBadge(title: tier) }
                    }
                    if let line = idLine {
                        Text(verbatim: line).font(.caption).foregroundStyle(Palette.secondary).lineLimit(1)
                    }
                }
                Spacer(minLength: 0)
            }
            if let credits = summary.credits {
                VStack(alignment: .leading, spacing: 4) {
                    HStack(alignment: .firstTextBaseline, spacing: 6) {
                        Text(verbatim: LynxceBackend.formatCredits(credits))
                            .font(.system(size: 32, weight: .bold, design: .rounded))
                            .monospacedDigit()
                        Text("credits.unit").font(.subheadline).foregroundStyle(Palette.secondary)
                    }
                    HStack(spacing: 14) {
                        if let expiring = summary.expiring, expiring > 0 {
                            Text(verbatim: expiringLine(expiring)).foregroundStyle(.orange)
                        }
                        if let permanent = summary.permanent {
                            Text(verbatim: L("account.permanent %@", LynxceBackend.formatCredits(permanent)))
                                .foregroundStyle(Palette.secondary)
                        }
                    }
                    .font(.caption)
                    .lineLimit(1)
                    .minimumScaleFactor(0.8)
                }
            }
            if let expiry = summary.signupExpiryDay {
                Text(verbatim: L("account.signupExpiry %@", expiry)).font(.caption).foregroundStyle(Palette.secondary)
            }
            if let openCredits {
                Button(action: openCredits) {
                    HStack {
                        Text("account.creditsAndUsage").font(.subheadline.weight(.semibold))
                        Spacer()
                        Image(systemName: "chevron.right").font(.footnote.weight(.semibold))
                    }
                    .padding(.horizontal, 14)
                    .padding(.vertical, 11)
                    .background(Palette.background.opacity(0.7), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                    .foregroundStyle(Palette.text)
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("accountCredits")
            }
        }
        .padding(16)
        .background(
            LinearGradient(
                colors: [Palette.brand.opacity(0.16), Color.purple.opacity(0.06)],
                startPoint: .topLeading, endPoint: .bottomTrailing
            ),
            in: RoundedRectangle(cornerRadius: 20, style: .continuous)
        )
        .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).stroke(Palette.brand.opacity(0.22), lineWidth: 1))
    }

    private var idLine: String? {
        let until = summary.memberUntil.map { L("account.until %@", Self.day.string(from: $0)) }
        let id = summary.accountHint.map { L("account.lynxceId %@", $0) }
        let parts = [id, until].compactMap { $0 }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    private func expiringLine(_ credits: Double) -> String {
        let amount = LynxceBackend.formatCredits(credits)
        guard let on = summary.expiringOn else { return L("account.expiring %@", amount) }
        return L("account.expiringOn %@ %@", amount, Self.day.string(from: on))
    }

    private static let day: DateFormatter = {
        let formatter = DateFormatter()
        formatter.setLocalizedDateFormatFromTemplate("MMdd")
        return formatter
    }()
}

/// The Lynxce avatar (or the name's first letter on rose) with the small Lynxce mark.
struct LynxceAvatar: View {
    let name: String
    let url: URL?
    var localImage: Data? = nil
    var size: CGFloat = 52
    var branded = true

    var body: some View {
        ZStack(alignment: .bottomTrailing) {
            Group {
                if let localImage, let image = UIImage(data: localImage) {
                    Image(uiImage: image).resizable().scaledToFill()
                } else if let url {
                    AsyncImage(url: url) { phase in
                        if case .success(let image) = phase {
                            image.resizable().scaledToFill()
                        } else {
                            initial
                        }
                    }
                    .id(url)
                } else {
                    initial
                }
            }
            .frame(width: size, height: size)
            .clipShape(Circle())
            if branded {
                VendorLogo(company: "lynxce", size: size * 0.36)
                    .clipShape(Circle())
                    .overlay(Circle().stroke(Palette.background, lineWidth: 2))
                    .offset(x: 3, y: 3)
            }
        }
        .accessibilityHidden(true)
    }

    private var initial: some View {
        ZStack {
            LinearGradient(colors: [Palette.brandButtonTop, Palette.brandButtonBottom], startPoint: .top, endPoint: .bottom)
            Text(verbatim: String(name.trimmingCharacters(in: .whitespacesAndNewlines).prefix(1)))
                .font(.system(size: size * 0.42, weight: .semibold, design: .rounded))
                .foregroundStyle(.white)
        }
    }
}

/// The member tier, gold like the desktop's badge.
struct TierBadge: View {
    let title: String

    var body: some View {
        Text(verbatim: title)
            .font(.caption2.weight(.bold))
            .foregroundStyle(Color(red: 0.55, green: 0.35, blue: 0.02))
            .padding(.horizontal, 7)
            .padding(.vertical, 2)
            .background(Color(red: 1, green: 0.86, blue: 0.5), in: RoundedRectangle(cornerRadius: 6, style: .continuous))
            .lineLimit(1)
    }
}
