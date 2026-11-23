import PhotosUI
import SwiftUI

/// One Bot's chat, pushed from the directory.
struct ChatScreen: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @Environment(\.horizontalSizeClass) private var sizeClass
    let chat: ChatSession
    @State private var showHistory = false
    @State private var showVoice = false
    @State private var editing = false

    var body: some View {
        VStack(spacing: 0) {
            topBar
            if model.showsLowBalanceBanner {
                LowBalanceBanner().transition(.move(edge: .top).combined(with: .opacity))
            }
            ConversationView(chat: chat)
            if let pause = chat.pause, !chat.isStreaming {
                HitlCard(chat: chat, pause: pause)
                    .id(pause.id)
            }
            Composer(chat: chat)
        }
        .animation(.snappy, value: chat.pause)
        .animation(.snappy, value: chat.isStreaming)
        .animation(.snappy, value: model.showsLowBalanceBanner)
        .background(Palette.background.ignoresSafeArea())
        .toolbar(.hidden, for: .navigationBar)
        .tint(chat.bot.accent)
        .sheet(isPresented: $showHistory) { HistorySheet(chat: chat) }
        .sheet(isPresented: $editing) { BotEditor(bot: chat.bot) }
        .fullScreenCover(isPresented: $showVoice) { VoiceModeView(chat: chat) }
        .onAppear {
            model.lastBotId = chat.bot.id
            model.showing(chat.bot)
        }
        .onDisappear { model.hiding(chat.bot) }
        // A phone-local Bot deleted from its editor closes its chat too.
        .onChange(of: LocalBots.shared.custom.map(\.id)) { _, ids in
            if chat.bot.isLocal && !ids.contains(chat.bot.id) { dismiss() }
        }
        .task { await chat.reloadConversations() }
        // A light tap when a reply starts, a success buzz when it lands.
        .onChange(of: chat.isStreaming) { _, streaming in
            streaming ? Haptics.tap() : Haptics.success()
        }
    }

    private var topBar: some View {
        HStack(spacing: 4) {
            // Side by side with the directory (iPad, an unfolded iPhone Duo) there is nothing to go back to.
            if sizeClass != .regular {
                Button { dismiss() } label: {
                    Image(systemName: "chevron.left").font(.title3.weight(.semibold)).frame(width: 44, height: 44)
                }
                .accessibilityLabel(Text("common.back"))
            }
            Spacer(minLength: 0)
            Button { if model.canEdit(chat.bot) { editing = true } } label: {
                HStack(spacing: 8) {
                    CharacterView(look: chat.bot.look, size: 30, motion: chat.motion, seed: chat.bot.id)
                    VStack(alignment: .leading, spacing: 0) {
                        Text(chat.bot.name).font(.headline).lineLimit(1)
                        Group {
                            if chat.isStreaming {
                                Text(chat.motion == .thinking ? "chat.thinking" : "chat.typing")
                                    .foregroundStyle(chat.bot.accent)
                            } else if let title = chat.title, !title.isEmpty {
                                Text(title).foregroundStyle(Palette.secondary)
                            }
                        }
                        .font(.caption2)
                        .lineLimit(1)
                        .transition(.opacity)
                    }
                    .frame(maxWidth: 180, alignment: .leading)
                }
                .animation(.snappy, value: chat.isStreaming)
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("botTitle")
            Spacer(minLength: 0)
            Button { showHistory = true } label: {
                Image(systemName: "clock.arrow.circlepath").font(.title3.weight(.medium)).frame(width: 40, height: 44)
            }
            .accessibilityLabel(Text("chat.history"))
            Button { showVoice = true } label: {
                Image(systemName: "waveform").font(.title3.weight(.medium)).frame(width: 40, height: 44)
            }
            .accessibilityLabel(Text("voice.title"))
            Button {
                Haptics.tap()
                withAnimation(.snappy) { chat.newChat() }
            } label: {
                Image(systemName: "square.and.pencil").font(.title3.weight(.medium)).frame(width: 40, height: 44)
            }
            .accessibilityLabel(Text("chat.new"))
            .disabled(chat.messages.isEmpty && !chat.isStreaming)
        }
        .foregroundStyle(Palette.text)
        .padding(.horizontal, 6)
        .background(Palette.background)
        .zIndex(1)
    }
}

/// Messages of the open conversation, or the Bot's welcome when it is empty.
struct ConversationView: View {
    let chat: ChatSession
    @State private var atBottom = true
    @State private var viewing: ImageGallery?

    var body: some View {
        Group {
            if chat.messages.isEmpty {
                if chat.isLoading {
                    ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {
                    EmptyChat(chat: chat)
                }
            } else {
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 18) {
                            ForEach(Array(chat.messages.enumerated()), id: \.element.id) { index, message in
                                let previous = index > 0 ? chat.messages[index - 1].createdAt : nil
                                if TimeLabel.needsSeparator(message.createdAt, after: previous) {
                                    TimeSeparator(date: message.createdAt)
                                }
                                MessageRow(
                                    chat: chat, message: message, isLast: message.id == chat.messages.last?.id,
                                    onImage: { images, index in viewing = ImageGallery(images: images, index: index) }
                                )
                                .id(message.id)
                            }
                            ForEach(chat.queued) { queued in
                                QueuedRow(message: queued) { withAnimation(.snappy) { chat.unqueue(queued) } }
                            }
                            Color.clear.frame(height: 8).id("bottom")
                                .onAppear { atBottom = true }
                                .onDisappear { atBottom = false }
                        }
                        .padding(.horizontal, 16)
                        .padding(.top, 8)
                    }
                    .scrollDismissesKeyboard(.interactively)
                    .defaultScrollAnchor(.bottom)
                    .onChange(of: chat.messages.last?.text) {
                        // Follow the stream only while the reader is at the end.
                        if atBottom { proxy.scrollTo("bottom", anchor: .bottom) }
                    }
                    .onChange(of: chat.messages.count + chat.queued.count) {
                        withAnimation(.snappy) { proxy.scrollTo("bottom", anchor: .bottom) }
                    }
                    .overlay(alignment: .bottom) {
                        if !atBottom {
                            Button {
                                withAnimation(.snappy) { proxy.scrollTo("bottom", anchor: .bottom) }
                            } label: {
                                Image(systemName: "arrow.down")
                                    .font(.callout.weight(.semibold))
                                    .frame(width: 38, height: 38)
                                    .background(Palette.raised, in: Circle())
                                    .overlay(Circle().stroke(Palette.hairline, lineWidth: 0.5))
                                    .shadow(color: .black.opacity(0.2), radius: 6, y: 2)
                            }
                            .foregroundStyle(Palette.text)
                            .padding(.bottom, 8)
                            .transition(.scale.combined(with: .opacity))
                            .accessibilityLabel(Text("chat.jumpToLatest"))
                        }
                    }
                    .animation(.snappy, value: atBottom)
                }
            }
        }
        .chatTextSize()
        .frame(maxHeight: .infinity)
        .overlay(alignment: .top) {
            if let error = chat.error {
                ErrorBanner(text: error) { withAnimation { chat.error = nil } }
            }
        }
        .animation(.snappy, value: chat.error)
        .task(id: chat.error) {
            // A message with a link stays until closed, so the link can be tapped.
            guard let error = chat.error, !LinkedText.hasLink(error) else { return }
            try? await Task.sleep(for: .seconds(4))
            withAnimation { chat.error = nil }
        }
        .fullScreenCover(item: $viewing) { gallery in ImageViewer(gallery: gallery) }
    }
}

/// A message written while the Bot was replying; it goes out when the reply ends.
private struct QueuedRow: View {
    var message: ChatMessage
    var remove: () -> Void

    var body: some View {
        HStack {
            Spacer(minLength: 48)
            VStack(alignment: .trailing, spacing: 4) {
                if !message.text.isEmpty {
                    Text(message.text)
                        .padding(.horizontal, 16)
                        .padding(.vertical, 11)
                        .background(Palette.surface.opacity(0.6), in: RoundedRectangle(cornerRadius: 20, style: .continuous))
                        .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).strokeBorder(Palette.hairline, style: StrokeStyle(lineWidth: 1, dash: [4, 3])))
                        .foregroundStyle(Palette.secondary)
                } else if !message.images.isEmpty {
                    Label("chat.queued.photos \(message.images.count)", systemImage: "photo")
                        .font(.footnote).foregroundStyle(Palette.secondary)
                }
                Button(action: remove) {
                    HStack(spacing: 4) {
                        Image(systemName: "clock")
                        Text("chat.queued")
                        Image(systemName: "xmark.circle.fill")
                    }
                    .font(.caption2)
                    .foregroundStyle(Palette.secondary)
                }
                .buttonStyle(.plain)
                .accessibilityLabel(Text("chat.queued.cancel"))
            }
        }
        .transition(.opacity)
    }
}

/// A short error at the top of a timeline; tap to dismiss. A server message with a link (e.g. the
/// Lynxce recharge page) keeps the link tappable and gets a close button instead.
struct ErrorBanner: View {
    var text: String
    var dismiss: () -> Void

    var body: some View {
        let linked = LinkedText.hasLink(text)
        HStack(spacing: 6) {
            Image(systemName: "exclamationmark.circle.fill")
            LinkedText(text: text).lineLimit(linked ? 3 : 2)
            if linked {
                Button(action: dismiss) {
                    Image(systemName: "xmark").font(.caption.weight(.semibold)).foregroundStyle(Palette.secondary)
                }
                .buttonStyle(.plain)
                .accessibilityLabel(Text("common.close"))
            }
        }
        .font(.footnote)
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
        .background(.regularMaterial, in: Capsule())
        .overlay(Capsule().stroke(.red.opacity(0.35), lineWidth: 0.5))
        .foregroundStyle(Palette.text)
        .contentShape(Capsule())
        .onTapGesture { if !linked { dismiss() } }
        .padding(.top, 8)
        .padding(.horizontal, 16)
        .transition(.move(edge: .top).combined(with: .opacity))
    }
}

/// Text whose URLs are tappable and open in an in-app Safari sheet.
struct LinkedText: View {
    var text: String
    @State private var opened: URL?

    var body: some View {
        Text(Self.attributed(text))
            .environment(\.openURL, OpenURLAction { url in
                opened = url
                return .handled
            })
            .sheet(item: $opened) { SafariView(url: $0).ignoresSafeArea() }
    }

    static func links(in text: String) -> [(range: Range<String.Index>, url: URL)] {
        guard let detector = try? NSDataDetector(types: NSTextCheckingResult.CheckingType.link.rawValue) else { return [] }
        return detector.matches(in: text, range: NSRange(text.startIndex..., in: text)).compactMap { match in
            guard let url = match.url, ["http", "https"].contains(url.scheme ?? ""),
                  let range = Range(match.range, in: text) else { return nil }
            return (range, url)
        }
    }

    static func hasLink(_ text: String) -> Bool { !links(in: text).isEmpty }

    static func attributed(_ text: String) -> AttributedString {
        var out = AttributedString()
        var cursor = text.startIndex
        for link in links(in: text) {
            out += AttributedString(text[cursor..<link.range.lowerBound])
            var piece = AttributedString(text[link.range])
            piece.link = link.url
            piece.underlineStyle = .single
            out += piece
            cursor = link.range.upperBound
        }
        out += AttributedString(text[cursor...])
        return out
    }
}

struct TimeSeparator: View {
    var date: Date

    var body: some View {
        Text(TimeLabel.text(date))
            .font(.caption)
            .foregroundStyle(Palette.secondary)
            .frame(maxWidth: .infinity)
            .padding(.top, 4)
    }
}

private struct EmptyChat: View {
    let chat: ChatSession

    /// Built-in roles get their own starters; everyone else the general ones.
    static func suggestions(for bot: BotProfile) -> [String] {
        let roles = ["researcher", "engineer", "translator", "writer", "companion"]
        guard roles.contains(bot.id) else { return ["chat.suggest.plan", "chat.suggest.explain", "chat.suggest.write"] }
        return (1...3).map { "chat.suggest.\(bot.id).\($0)" }
    }

    var body: some View {
        VStack(spacing: 14) {
            Spacer()
            CharacterView(look: chat.bot.look, size: 168, motion: .idle, seed: chat.bot.id)
            Text("chat.greeting \(chat.bot.name)")
                .font(.system(.title2, design: .rounded).weight(.semibold))
                .foregroundStyle(Palette.text)
            if let subtitle = chat.bot.subtitle {
                Text(subtitle).font(.subheadline).foregroundStyle(Palette.secondary)
                    .multilineTextAlignment(.center).lineLimit(3).padding(.horizontal, 32)
            }
            Spacer()
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(Self.suggestions(for: chat.bot), id: \.self) { key in
                        let text = L(key)
                        Button(text) { chat.send(text) }.buttonStyle(PillButtonStyle())
                    }
                }
                .padding(.horizontal, 16)
            }
            .padding(.bottom, 8)
        }
    }
}

struct MessageRow: View {
    @Environment(AppModel.self) private var model
    @Environment(Preferences.self) private var preferences
    let chat: ChatSession
    var message: ChatMessage
    var isLast: Bool
    var onImage: ([Data], Int) -> Void = { _, _ in }
    @State private var showThinking: Bool?

    var body: some View {
        switch message.role {
        case .user: userBubble
        case .system:
            Text(message.text)
                .font(.caption)
                .foregroundStyle(Palette.secondary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: .infinity)
        case .assistant: assistant
        }
    }

    private var thinkingOpen: Bool { showThinking ?? preferences.expandThinking }

    private var userBubble: some View {
        HStack {
            Spacer(minLength: 48)
            VStack(alignment: .trailing, spacing: 6) {
                if !message.images.isEmpty {
                    HStack(spacing: 6) {
                        ForEach(Array(message.images.enumerated()), id: \.offset) { index, data in
                            if let image = UIImage(data: data) {
                                Button { onImage(message.images, index) } label: {
                                    Image(uiImage: image).resizable().scaledToFill()
                                        .frame(width: 96, height: 96).clipShape(RoundedRectangle(cornerRadius: 14))
                                }
                                .buttonStyle(.plain)
                            }
                        }
                    }
                }
                if !message.text.isEmpty {
                    Text(message.text)
                        .padding(.horizontal, 16)
                        .padding(.vertical, 11)
                        .background(Palette.surface, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
                        .foregroundStyle(Palette.text)
                        .contextMenu {
                            Button("common.copy", systemImage: "doc.on.doc") { Clipboard.copy(message.text) }
                            if !chat.isStreaming {
                                Button("chat.edit", systemImage: "pencil") { chat.edit(message) }
                            }
                        }
                }
            }
        }
    }

    private var assistant: some View {
        HStack(alignment: .top, spacing: 10) {
            CharacterView(look: chat.bot.look, size: 26, motion: message.status == .streaming ? chat.motion : .idle, seed: chat.bot.id)
                .padding(.top, 1)
            VStack(alignment: .leading, spacing: 8) {
                if !message.thinking.isEmpty {
                    Button { withAnimation(.snappy) { showThinking = !thinkingOpen } } label: {
                        HStack(spacing: 4) {
                            Image(systemName: "sparkles").font(.caption)
                            Text(message.status == .streaming && message.text.isEmpty ? "chat.thinking" : "chat.thought")
                            Image(systemName: thinkingOpen ? "chevron.up" : "chevron.down").font(.caption2.weight(.bold))
                        }
                        .font(.subheadline)
                        .foregroundStyle(Palette.secondary)
                    }
                    .buttonStyle(.plain)
                    if thinkingOpen {
                        Text(message.thinking)
                            .font(.footnote)
                            .foregroundStyle(Palette.secondary)
                            .padding(.leading, 10)
                            .overlay(alignment: .leading) { Capsule().fill(Palette.hairline).frame(width: 2) }
                            .textSelection(.enabled)
                    }
                }
                if !message.tools.isEmpty {
                    FlowChips(tools: message.tools)
                }
                if !message.text.isEmpty {
                    MarkdownText(text: message.text).foregroundStyle(Palette.text)
                } else if message.status == .streaming && message.thinking.isEmpty && message.tools.isEmpty {
                    TypingDots()
                }
                if message.status.isStoppedByLynxce {
                    // Not an error: top up (or wait for the daily reset), then "Continue" re-runs the turn like retry does.
                    OutOfCreditsCard(
                        reason: message.status == .dailyLimit ? .dailyLimit : .outOfCredits,
                        canContinue: isLast && !chat.isStreaming
                    ) { chat.retry() }
                } else if case .failed(let reason) = message.status {
                    HStack(spacing: 10) {
                        Label { LinkedText(text: reason) } icon: { Image(systemName: "exclamationmark.triangle") }
                            .font(.footnote).foregroundStyle(.red)
                        if isLast { Button("chat.retry") { chat.retry() }.font(.footnote.weight(.semibold)) }
                    }
                } else if message.status == .done && !message.text.isEmpty {
                    ReplyActions(chat: chat, message: message, isLast: isLast)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .contextMenu {
            Button("common.copy", systemImage: "doc.on.doc") { Clipboard.copy(message.text) }
            Button("chat.readAloud", systemImage: "speaker.wave.2") {
                Speaker.shared.speak(message.text, backend: model.backend, id: message.id)
            }
            ShareLink(item: message.text) { Label("common.share", systemImage: "square.and.arrow.up") }
            if isLast && message.status != .streaming && !message.status.isStoppedByLynxce {
                Button("chat.retry", systemImage: "arrow.clockwise") { chat.retry() }
            }
        }
    }
}

/// Copy / read aloud / share / retry under a finished reply.
private struct ReplyActions: View {
    @Environment(AppModel.self) private var model
    let chat: ChatSession
    var message: ChatMessage
    var isLast: Bool
    @State private var copied = false
    private var speaker: Speaker { Speaker.shared }

    var body: some View {
        let speaking = speaker.speakingId == message.id
        HStack(spacing: 2) {
            action(copied ? "checkmark" : "doc.on.doc", label: "common.copy") {
                Clipboard.copy(message.text)
                copied = true
                Task {
                    try? await Task.sleep(for: .seconds(1.5))
                    copied = false
                }
            }
            action(speaking ? "stop.circle" : "speaker.wave.2", label: speaking ? "chat.stopReading" : "chat.readAloud") {
                if speaking {
                    speaker.stop()
                } else {
                    speaker.speak(message.text, backend: model.backend, id: message.id)
                }
            }
            ShareLink(item: message.text) {
                Image(systemName: "square.and.arrow.up").frame(width: 34, height: 30)
            }
            .accessibilityLabel(Text("common.share"))
            if isLast && !chat.isStreaming {
                action("arrow.clockwise", label: "chat.retry") { chat.retry() }
            }
        }
        .font(.footnote.weight(.medium))
        .foregroundStyle(Palette.secondary)
        .padding(.leading, -8)
        .contentTransition(.symbolEffect(.replace))
    }

    private func action(_ symbol: String, label: LocalizedStringKey, perform: @escaping () -> Void) -> some View {
        Button(action: perform) {
            Image(systemName: symbol).frame(width: 34, height: 30)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(Text(label))
    }
}

enum Clipboard {
    static func copy(_ text: String) {
        UIPasteboard.general.string = text
        Haptics.success()
    }
}

/// Tool steps of one reply: the running step while working, a one-line summary once done.
private struct FlowChips: View {
    var tools: [ToolStep]
    @State private var expanded = false

    private var running: ToolStep? { tools.last { !$0.done } }
    private var distinct: Int { Set(tools.map(\.name)).count }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if tools.count <= 2 {
                ForEach(tools) { chip($0) }
            } else {
                Button { withAnimation(.snappy) { expanded.toggle() } } label: {
                    HStack(spacing: 6) {
                        if let running {
                            ProgressView().controlSize(.mini)
                            Text("chat.tool.running \(running.name)")
                        } else {
                            Image(systemName: "checkmark.circle.fill").foregroundStyle(.green)
                            Text("chat.tool.summary \(distinct) \(tools.count)")
                        }
                        Image(systemName: expanded ? "chevron.up" : "chevron.down").font(.caption2.weight(.bold))
                    }
                    .font(.caption)
                    .foregroundStyle(Palette.secondary)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 5)
                    .background(Palette.surface, in: Capsule())
                }
                .buttonStyle(.plain)
                if expanded {
                    ForEach(tools) { chip($0) }.padding(.leading, 10)
                }
            }
        }
    }

    private func chip(_ tool: ToolStep) -> some View {
        HStack(spacing: 6) {
            if tool.done {
                Image(systemName: "checkmark.circle.fill").foregroundStyle(.green)
            } else {
                ProgressView().controlSize(.mini)
            }
            Text(tool.done ? "chat.tool.done \(tool.name)" : "chat.tool.running \(tool.name)")
        }
        .font(.caption)
        .foregroundStyle(Palette.secondary)
        .padding(.horizontal, 10)
        .padding(.vertical, 5)
        .background(Palette.surface, in: Capsule())
    }
}

struct TypingDots: View {
    var body: some View {
        TimelineView(.animation) { timeline in
            let t = timeline.date.timeIntervalSinceReferenceDate
            HStack(spacing: 5) {
                ForEach(0..<3) { i in
                    Circle().fill(Palette.secondary).frame(width: 7, height: 7)
                        .opacity(0.35 + 0.65 * (sin(t * 5 - Double(i) * 0.8) + 1) / 2)
                }
            }
            .padding(.vertical, 6)
        }
    }
}

/// Floating pill composer: photos, text, mic / send / stop.
struct Composer: View {
    @Environment(AppModel.self) private var model
    @Bindable var chat: ChatSession
    @State private var photos: [PhotosPickerItem] = []
    @State private var images: [Data] = []
    @State private var recorder = VoiceRecorder()
    @FocusState private var focused: Bool

    var body: some View {
        VStack(spacing: 8) {
            if !images.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        ForEach(Array(images.enumerated()), id: \.offset) { index, data in
                            ZStack(alignment: .topTrailing) {
                                if let image = UIImage(data: data) {
                                    Image(uiImage: image).resizable().scaledToFill()
                                        .frame(width: 64, height: 64).clipShape(RoundedRectangle(cornerRadius: 12))
                                }
                                Button { images.remove(at: index) } label: {
                                    Image(systemName: "xmark.circle.fill").symbolRenderingMode(.palette)
                                        .foregroundStyle(.white, .black.opacity(0.6))
                                }
                                .padding(3)
                            }
                        }
                    }
                    .padding(.horizontal, 20)
                }
            }
            HStack(alignment: .bottom, spacing: 6) {
                PhotosPicker(selection: $photos, maxSelectionCount: 4, matching: .images) {
                    Image(systemName: "plus").font(.title3.weight(.medium)).frame(width: 40, height: 40)
                }
                .foregroundStyle(Palette.text)
                .accessibilityLabel(Text("chat.attach"))
                TextField(composerPrompt, text: $chat.draft, axis: .vertical)
                    .lineLimit(1...6)
                    .focused($focused)
                    .padding(.vertical, 10)
                    .accessibilityIdentifier("composer")
                trailingButton
            }
            .padding(.leading, 6)
            .padding(.trailing, 5)
            .padding(.vertical, 4)
            .background(Palette.surface, in: RoundedRectangle(cornerRadius: 26, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 26, style: .continuous).stroke(Palette.hairline, lineWidth: 0.5))
            .padding(.horizontal, 12)
            .padding(.bottom, 8)
        }
        .chatTextSize()
        .onChange(of: chat.focusRequest) { focused = true }
        .task(id: recorder.failure) {
            guard recorder.failure != nil else { return }
            try? await Task.sleep(for: .seconds(4))
            recorder.clearFailure()
        }
        .onChange(of: photos) {
            let picked = photos
            photos = []
            Task {
                for item in picked {
                    if let data = try? await item.loadTransferable(type: Data.self), let jpeg = ImageResizer.jpeg(data) {
                        images.append(jpeg)
                    }
                }
            }
        }
    }

    private var composerPrompt: String {
        if recorder.isRecording { return L("chat.listening") }
        if let pause = chat.pause { return L(pause.isQuestion ? "hitl.ask.composer" : "hitl.composer") }
        if chat.isStreaming { return L("chat.placeholder.queue") }
        return recorder.failure ?? L("chat.placeholder")
    }

    @ViewBuilder
    private var trailingButton: some View {
        let empty = chat.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && images.isEmpty
        if chat.isStreaming && empty {
            Button { chat.stop() } label: {
                Image(systemName: "stop.fill").font(.callout).frame(width: 36, height: 36)
                    .background(Palette.text, in: Circle()).foregroundStyle(Palette.background)
            }
            .accessibilityLabel(Text("chat.stop"))
            .padding(.bottom, 2)
        } else if empty {
            Button(action: toggleDictation) {
                Image(systemName: recorder.isRecording ? "stop.circle.fill" : "mic")
                    .font(.title3)
                    .frame(width: 40, height: 40)
                    .foregroundStyle(recorder.isRecording ? .red : Palette.text)
            }
            .accessibilityLabel(Text("chat.dictate"))
        } else {
            Button(action: send) {
                Image(systemName: "arrow.up").font(.callout.weight(.bold)).frame(width: 36, height: 36)
                    .background(Palette.text, in: Circle()).foregroundStyle(Palette.background)
            }
            .accessibilityIdentifier("send")
            .padding(.bottom, 2)
        }
    }

    private func send() {
        Haptics.tap()
        chat.send(chat.draft, images: images)
        chat.draft = ""
        images = []
    }

    private func toggleDictation() {
        Task {
            if recorder.isRecording {
                if let heard = await recorder.finish(backend: model.backend), !heard.isEmpty {
                    chat.draft = chat.draft.isEmpty ? heard : chat.draft + " " + heard
                    focused = true
                }
            } else {
                await recorder.start()
            }
        }
    }
}

enum ImageResizer {
    /// Downscale photos to 1600 px JPEG so uploads stay small.
    static func jpeg(_ data: Data, maxSide: CGFloat = 1600) -> Data? {
        guard let image = UIImage(data: data) else { return nil }
        let scale = min(1, maxSide / max(image.size.width, image.size.height))
        let size = CGSize(width: image.size.width * scale, height: image.size.height * scale)
        let format = UIGraphicsImageRendererFormat.default()
        format.scale = 1
        let resized = UIGraphicsImageRenderer(size: size, format: format).image { _ in image.draw(in: CGRect(origin: .zero, size: size)) }
        return resized.jpegData(compressionQuality: 0.82)
    }
}
