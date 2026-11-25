import SwiftUI
import UIKit
import WebKit

/// The floating view of a Bot's cloud computer in its chat (plan §12.7, like the web float):
/// a small 16:9 card while the Bot works on the computer, a pill when minimised, full screen
/// with take-over on tap, and closed until the header button shows it again.
@Observable
final class CloudFloat {
    enum Mode { case hidden, pill, card }

    let server: ServerBackend
    let botId: String
    /// The server has cloud computers (status answers instead of 404).
    private(set) var available = false
    private(set) var status: ServerBackend.ComputerStatus?
    private(set) var window: String?
    private(set) var thumbnail: UIImage?
    var mode: Mode = .hidden
    var expanded = false
    var corner: Corner {
        didSet { UserDefaults.standard.set(corner.rawValue, forKey: "octop.cloudFloat.corner") }
    }
    /// Closed by the user: no auto-show in this Bot's chat until the header button.
    private(set) var closed: Bool {
        didSet { UserDefaults.standard.set(closed, forKey: "octop.cloudFloat.closed.\(botId)") }
    }
    /// Minimised by the user: later turns of this chat only show the pill.
    private var pillOnly = false
    /// Opened from the header while the computer is off: keep the card up anyway.
    private var pinned = false
    private var idleSince: Date?

    /// A turn ends: the card shrinks to the pill after this long without actions.
    static let idleToPill: TimeInterval = 30
    static let pollInterval: Duration = .seconds(3)

    init(server: ServerBackend, botId: String) {
        self.server = server
        self.botId = botId
        corner = Corner(rawValue: UserDefaults.standard.string(forKey: "octop.cloudFloat.corner") ?? "") ?? .bottomTrailing
        closed = UserDefaults.standard.bool(forKey: "octop.cloudFloat.closed.\(botId)")
    }

    var running: Bool { status?.state == .running }
    var busy: Bool { running && status?.busy == true }

    /// Polls while the chat is on screen (the caller's task is cancelled when it leaves).
    func run() async {
        while !Task.isCancelled {
            await refresh()
            try? await Task.sleep(for: Self.pollInterval)
        }
    }

    func refresh() async {
        let next: ServerBackend.ComputerStatus
        do {
            next = try await server.computerStatus(botId)
        } catch let error as APIError where error.status == 404 {
            available = false
            mode = .hidden
            return
        } catch {
            return
        }
        available = true
        status = next
        guard next.state == .running else {
            thumbnail = nil
            window = nil
            if !pinned { mode = .hidden }
            return
        }
        if next.busy {
            idleSince = nil
            if !closed, mode == .hidden || (mode == .pill && !pillOnly) { mode = pillOnly ? .pill : .card }
        } else {
            let since = idleSince ?? Date()
            idleSince = since
            if mode == .card, !pinned, Date().timeIntervalSince(since) > Self.idleToPill { mode = .pill }
            if mode == .hidden, !closed { mode = .pill }
        }
        if mode == .card, !expanded, !Task.isCancelled, let glance = try? await server.glance(botId), !Task.isCancelled {
            window = glance.window
            if let image = glance.image { thumbnail = image }
        }
    }

    /// The chat header's button: show the card, or close it when it is showing.
    func toggle() {
        if mode == .hidden || closed {
            closed = false
            pinned = true
            pillOnly = false
            mode = .card
            // The computer is off: the icon starts it, full screen saying so until the desktop is up.
            if available, !running { expanded = true }
            Task { await refresh() }
        } else {
            close()
        }
    }

    func close() {
        closed = true
        pinned = false
        mode = .hidden
    }

    func minimise() {
        pillOnly = true
        pinned = false
        mode = .pill
    }

    func open() {
        pinned = true
        pillOnly = false
        mode = .card
    }

    /// What the Bot just did, for the card's header.
    var activityText: LocalizedStringKey {
        guard running else { return "computer.float.off" }
        if status?.takeover == true { return "computer.float.yours" }
        guard busy else { return "computer.float.idle" }
        switch status?.activity {
        case "screenshot": return "computer.activity.screenshot"
        case "click": return "computer.activity.click"
        case "type": return "computer.activity.type"
        case "key": return "computer.activity.key"
        case "scroll": return "computer.activity.scroll"
        case "command": return "computer.activity.command"
        case "file": return "computer.activity.file"
        default: return "computer.float.busy"
        }
    }
}

enum Corner: String, CaseIterable {
    case topLeading, topTrailing, bottomLeading, bottomTrailing
}

/// The card or pill, draggable to the four corners of the chat.
struct CloudFloatOverlay: View {
    @Bindable var float: CloudFloat
    let bot: BotProfile
    @State private var drag: CGSize = .zero
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private static let cardWidth: CGFloat = 208
    private static let margin: CGFloat = 12

    var body: some View {
        GeometryReader { geo in
            if float.mode != .hidden {
                content
                    .fixedSize()
                    .modifier(Placed(corner: float.corner, container: geo.size, margin: Self.margin))
                    .offset(drag)
                    .gesture(
                        DragGesture(minimumDistance: 8)
                            .onChanged { drag = $0.translation }
                            .onEnded { value in
                                let corner = nearest(to: value.predictedEndLocation, from: value.startLocation, in: geo.size)
                                withAnimation(reduceMotion ? nil : .spring(response: 0.35, dampingFraction: 0.8)) {
                                    float.corner = corner
                                    drag = .zero
                                }
                            }
                    )
                    .transition(.scale(scale: 0.85).combined(with: .opacity))
            }
        }
        .animation(reduceMotion ? nil : .snappy, value: float.mode)
    }

    @ViewBuilder private var content: some View {
        switch float.mode {
        case .card: card
        case .pill: pill
        case .hidden: EmptyView()
        }
    }

    private var title: String {
        if let window = float.window, !window.isEmpty { return window }
        return bot.name
    }

    private var card: some View {
        VStack(spacing: 0) {
            HStack(spacing: 6) {
                Image(systemName: "desktopcomputer").font(.caption.weight(.semibold))
                VStack(alignment: .leading, spacing: 0) {
                    Text(title).font(.caption.weight(.semibold)).lineLimit(1)
                    Text(float.activityText).font(.caption2).foregroundStyle(Palette.secondary).lineLimit(1)
                }
                Spacer(minLength: 4)
                headerButton("arrow.up.left.and.arrow.down.right", label: "computer.float.expand") { float.expanded = true }
                headerButton("minus", label: "computer.float.minimise") { float.minimise() }
                headerButton("xmark", label: "computer.float.close") { float.close() }
            }
            .padding(.leading, 10)
            .padding(.trailing, 4)
            .frame(minHeight: 44)
            screen
                .frame(width: Self.cardWidth, height: Self.cardWidth * 9 / 16)
                .clipShape(RoundedRectangle(cornerRadius: 8))
                .padding([.horizontal, .bottom], 6)
                .onTapGesture { float.expanded = true }
        }
        .frame(width: Self.cardWidth + 12)
        .foregroundStyle(Palette.text)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 14))
        .overlay(glow)
        .shadow(color: .black.opacity(0.18), radius: 16, y: 6)
        .accessibilityIdentifier("cloudFloatCard")
    }

    @ViewBuilder private var screen: some View {
        ZStack {
            Color.black
            if let image = float.thumbnail {
                Image(uiImage: image).resizable().aspectRatio(16 / 9, contentMode: .fit)
            } else {
                Text(float.running ? "computer.float.loading" : "computer.float.off")
                    .font(.caption2)
                    .foregroundStyle(.white.opacity(0.7))
                    .multilineTextAlignment(.center)
                    .padding(10)
            }
        }
    }

    /// A breathing accent edge while the Bot works; solid blue while the user has the computer.
    @ViewBuilder private var glow: some View {
        if float.status?.takeover == true {
            RoundedRectangle(cornerRadius: 14).stroke(Color.blue, lineWidth: 2)
        } else if float.busy {
            TimelineView(.animation(minimumInterval: 1 / 15, paused: reduceMotion)) { context in
                let phase = reduceMotion ? 1 : (sin(context.date.timeIntervalSinceReferenceDate * 2.4) + 1) / 2
                RoundedRectangle(cornerRadius: 14)
                    .stroke(bot.accent.opacity(0.45 + 0.55 * phase), lineWidth: 2)
                    .shadow(color: bot.accent.opacity(0.5 * phase), radius: 6)
            }
        }
    }

    private var pill: some View {
        HStack(spacing: 8) {
            Button { float.open() } label: {
                HStack(spacing: 8) {
                    if let image = float.thumbnail {
                        Image(uiImage: image).resizable().aspectRatio(16 / 9, contentMode: .fill)
                            .frame(width: 40, height: 24).clipShape(RoundedRectangle(cornerRadius: 4))
                    } else {
                        Image(systemName: "desktopcomputer").font(.caption.weight(.semibold))
                    }
                    Circle().fill(float.busy ? Color.green : Palette.secondary).frame(width: 7, height: 7)
                    Text(float.activityText).font(.caption.weight(.medium)).lineLimit(1)
                }
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("cloudFloatPill")
            Button { float.close() } label: {
                Image(systemName: "xmark").font(.caption2.weight(.bold)).frame(width: 22, height: 22)
            }
            .buttonStyle(.plain)
            .accessibilityLabel(Text("computer.float.close"))
        }
        .foregroundStyle(Palette.text)
        .padding(.leading, 8)
        .padding(.trailing, 4)
        .padding(.vertical, 6)
        .background(.regularMaterial, in: Capsule())
        .shadow(color: .black.opacity(0.15), radius: 10, y: 4)
    }

    private func headerButton(_ symbol: String, label: LocalizedStringKey, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: symbol).font(.caption.weight(.semibold)).frame(width: 44, height: 44).contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(Text(label))
    }

    /// The corner the card is thrown toward.
    private func nearest(to end: CGPoint, from start: CGPoint, in size: CGSize) -> Corner {
        let origin = Placed.origin(for: float.corner, container: size, margin: Self.margin)
        let x = origin.x + (end.x - start.x)
        let y = origin.y + (end.y - start.y)
        let left = x < size.width / 2
        let top = y < size.height / 2
        switch (top, left) {
        case (true, true): return .topLeading
        case (true, false): return .topTrailing
        case (false, true): return .bottomLeading
        case (false, false): return .bottomTrailing
        }
    }

    private struct Placed: ViewModifier {
        let corner: Corner
        let container: CGSize
        let margin: CGFloat

        func body(content: Content) -> some View {
            // The bottom corners clear the chat's suggestion chips and the HITL card's edge.
            content.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: alignment)
                .padding(.horizontal, margin)
                .padding(.top, margin)
                .padding(.bottom, margin + 52)
        }

        private var alignment: Alignment {
            switch corner {
            case .topLeading: .topLeading
            case .topTrailing: .topTrailing
            case .bottomLeading: .bottomLeading
            case .bottomTrailing: .bottomTrailing
            }
        }

        /// Roughly where the float's centre sits in that corner.
        static func origin(for corner: Corner, container: CGSize, margin: CGFloat) -> CGPoint {
            let x = corner == .topLeading || corner == .bottomLeading ? margin + 110 : container.width - margin - 110
            let y = corner == .topLeading || corner == .topTrailing ? margin + 80 : container.height - margin - 80
            return CGPoint(x: x, y: y)
        }
    }
}

/// The chat header's cloud computer button: shows or closes the float; a green dot while the Bot works.
struct CloudFloatToggle: View {
    let float: CloudFloat

    var body: some View {
        Button {
            Haptics.tap()
            withAnimation(.snappy) { float.toggle() }
        } label: {
            Image(systemName: "desktopcomputer")
                .font(.title3.weight(.medium))
                .frame(width: 40, height: 44)
                .overlay(alignment: .topTrailing) {
                    if float.busy {
                        Circle().fill(Color.green).frame(width: 8, height: 8).offset(x: -6, y: 10)
                    }
                }
        }
        .accessibilityLabel(Text("computer.float.toggle"))
        .accessibilityIdentifier("cloudFloatToggle")
    }
}

/// Full screen: the live screen page (noVNC) with take-over.
struct CloudScreenCover: View {
    let float: CloudFloat
    let bot: BotProfile
    @Environment(\.dismiss) private var dismiss
    @State private var url: URL?
    @State private var error: String?
    @State private var busy = false
    @State private var controlError: String?

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 8) {
                Button { dismiss() } label: {
                    Image(systemName: "chevron.down").font(.body.weight(.semibold)).frame(width: 40, height: 44)
                }
                .accessibilityLabel(Text("computer.float.minimise"))
                .accessibilityIdentifier("cloudScreenMinimise")
                VStack(alignment: .leading, spacing: 0) {
                    Text(float.window?.isEmpty == false ? float.window! : bot.name).font(.subheadline.weight(.semibold)).lineLimit(1)
                    Text(url == nil && error == nil && !float.running ? "computer.startingShort" : float.activityText).font(.caption2).foregroundStyle(Palette.secondary).lineLimit(1)
                }
                Spacer(minLength: 0)
                Button {
                    Task { await takeover(!(float.status?.takeover ?? false)) }
                } label: {
                    Label(float.status?.takeover == true ? "computer.handBack" : "computer.takeOver",
                          systemImage: float.status?.takeover == true ? "hand.raised.slash" : "hand.raised")
                        .font(.subheadline.weight(.semibold))
                }
                .buttonStyle(.borderedProminent)
                .tint(float.status?.takeover == true ? .blue : bot.accent)
                .disabled(busy || !float.running)
                .accessibilityIdentifier("cloudScreenTakeover")
            }
            .padding(.horizontal, 8)
            .foregroundStyle(Palette.text)
            if let error, url != nil {
                VStack {
                    Text(verbatim: error).font(.footnote)
                    Button("common.retry") { Task { await load(control: float.status?.takeover == true) } }
                }.padding(.horizontal)
            }
            if let controlError {
                Text(verbatim: controlError).font(.footnote).foregroundStyle(Palette.text).padding(.horizontal)
            }
            ZStack {
                Color.black
                if let url {
                    ScreenWebView(url: url).id(url)
                        .task(id: url) { await float.server.keepScreenBound(url, agent: float.botId) }
                } else if let error {
                    VStack(spacing: 12) {
                        Text(error).multilineTextAlignment(.center).foregroundStyle(.white)
                        Button("common.retry") { Task { await load(control: float.status?.takeover == true) } }
                            .buttonStyle(.bordered)
                            .tint(.white)
                            .accessibilityIdentifier("cloudScreenRetry")
                    }
                    .padding(32)
                } else {
                    // Opening the screen starts or resumes a computer that is off.
                    VStack(spacing: 14) {
                        ProgressView().tint(.white)
                        if !float.running {
                            Text("computer.starting").multilineTextAlignment(.center).foregroundStyle(.white.opacity(0.8))
                        }
                    }
                    .padding(32)
                }
            }
        }
        .background(Palette.background.ignoresSafeArea())
        .task { await load(control: float.status?.takeover == true) }
    }

    private func load(control: Bool) async {
        error = nil
        do {
            url = try await float.server.screenURL(float.botId, control: control)
            await float.refresh()
        } catch is CancellationError {
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func takeover(_ active: Bool) async {
        busy = true
        defer { busy = false }
        controlError = nil
        do {
            _ = try await float.server.setTakeover(float.botId, active: active)
        } catch is CancellationError {
            return
        } catch {
            controlError = error.localizedDescription
            return
        }
        Haptics.success()
        await float.refresh()
        await load(control: active)
    }
}

/// The screen page in a web view (noVNC needs a real browser engine).
private struct ScreenWebView: UIViewRepresentable {
    let url: URL

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.allowsInlineMediaPlayback = true
        let view = WKWebView(frame: .zero, configuration: config)
        view.isOpaque = false
        view.backgroundColor = .black
        view.scrollView.isScrollEnabled = false
        view.load(URLRequest(url: url))
        return view
    }

    func updateUIView(_ view: WKWebView, context: Context) {
        // Redirects consume a one-time ticket. Only a newly issued URL creates another view.
    }
}

extension ServerBackend {
    struct Glance {
        var window: String?
        var image: UIImage?
    }

    /// Front window and a small thumbnail of a running computer; never wakes it (nil while it is off).
    func glance(_ agentId: String) async throws -> Glance? {
        let path = "/api/octop-bot/computers/" + (agentId.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? agentId) + "/glance"
        do {
            let body = try await json(.get, path) as? [String: Any]
            let image = (body?["thumbnail"] as? String).flatMap { Data(base64Encoded: $0) }.flatMap(UIImage.init(data:))
            return Glance(window: body?["window"] as? String, image: image)
        } catch let error as APIError where error.status == 404 {
            return nil
        }
    }
}
