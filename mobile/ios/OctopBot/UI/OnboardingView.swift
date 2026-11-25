import SwiftUI

/// First screen: sign in with a Lynxce account (code or password), or use the app without an
/// account on the user's own model; a self-hosted server stays available below.
struct OnboardingView: View {
    @Environment(AppModel.self) private var model
    @State private var account = ""
    @State private var password = ""
    @State private var entry = CodeEntry()
    @State private var usePassword = false
    @State private var busy = false
    @State private var error: String?
    @State private var showServer = false
    @State private var ownModel = false
    @FocusState private var focus: Field?

    @State private var shakeAccount: CGFloat = 0
    @State private var shakeSecond: CGFloat = 0

    enum Field { case account, password, code }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    banner
                    header
                    form
                    divider
                    ownModelRow
                    Button("onboarding.server") { showServer = true }
                        .font(.subheadline.weight(.medium))
                        .foregroundStyle(Palette.secondary)
                        .frame(maxWidth: .infinity)
                        .accessibilityIdentifier("connectServer")
                }
                .padding(.horizontal, 20)
                .padding(.top, 8)
                .padding(.bottom, 28)
                .frame(maxWidth: 520)
                .frame(maxWidth: .infinity)
            }
            .scrollDismissesKeyboard(.interactively)
            .background(Palette.background.ignoresSafeArea())
            .toolbar(.hidden, for: .navigationBar)
            .navigationDestination(isPresented: $ownModel) { ModelSetupView() }
        }
        .sheet(isPresented: $showServer) { ServerConnectView() }
        .onAppear {
            // "Switch account or server" from Settings lands here with the server sheet open.
            if model.reopenServerSheet {
                model.reopenServerSheet = false
                showServer = true
            }
        }
    }

    /// The desktop's left-hand stage, folded into a banner on a phone: Chief and the headline.
    private var banner: some View {
        HStack(spacing: 14) {
            CharacterView(look: .chief, size: 88, motion: busy ? .working : .idle)
                .shadow(color: Color(red: 0.24, green: 0, blue: 0.08).opacity(0.3), radius: 14, y: 10)
            Text("onboarding.heroTitle")
                .font(.system(size: 26, weight: .bold))
                .foregroundStyle(.white)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 22)
        .frame(maxWidth: .infinity, minHeight: 148)
        .background(StageBackground().clipShape(RoundedRectangle(cornerRadius: 26, style: .continuous)))
        .accessibilityElement(children: .combine)
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("onboarding.title")
                .font(.system(size: 28, weight: .bold))
                .foregroundStyle(Palette.text)
            Text("onboarding.subtitle")
                .font(.subheadline)
                .foregroundStyle(Palette.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.top, 6)
    }

    private var target: LynxceBackend.CodeTarget? { LynxceBackend.CodeTarget(account) }

    /// Signing in with something missing points at the account field first, then the code or password.
    static func missingField(account: String, usePassword: Bool) -> Field {
        let accountMissing = usePassword
            ? account.trimmingCharacters(in: .whitespaces).isEmpty
            : LynxceBackend.CodeTarget(account) == nil
        return accountMissing ? .account : (usePassword ? .password : .code)
    }

    private var canSignIn: Bool {
        usePassword ? !account.isEmpty && password.count >= 8 : target != nil && entry.isComplete
    }

    /// One "phone or email" field (its icon follows what is typed), the code with "Get code" inside
    /// it, or the password; "Use password" swaps the two. New accounts come from a code sign-in.
    private var form: some View {
        VStack(alignment: .leading, spacing: 12) {
            if let notice = model.signedOutNotice {
                Text(notice)
                    .font(.footnote)
                    .foregroundStyle(Palette.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            HStack(spacing: 8) {
                VendorLogo(company: "lynxce", size: 22)
                Text("onboarding.lynxceAccount").font(.subheadline.weight(.semibold))
                Spacer(minLength: 8)
                Text("onboarding.recommendedSync")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(Palette.brandText)
                    .lineLimit(1)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 4)
                    .background(Palette.brand.opacity(0.1), in: Capsule())
            }
            HStack(spacing: 10) {
                Image(systemName: account.contains("@") ? "envelope" : "iphone")
                    .font(.body)
                    .foregroundStyle(Palette.secondary)
                    .frame(width: 22)
                    .contentTransition(.symbolEffect(.replace))
                TextField("onboarding.target", text: $account)
                    .textContentType(.username)
                    .keyboardType(.emailAddress)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .focused($focus, equals: .account)
                    .submitLabel(usePassword ? .next : .send)
                    .onSubmit { if usePassword { focus = .password } else { sendCode() } }
                    .onChange(of: account) {
                        entry.reset()
                        error = nil
                    }
                    .accessibilityIdentifier("account")
            }
            .signInFieldStyle(focused: focus == .account)
            .modifier(Shake(shakes: shakeAccount))
            Group {
                if usePassword {
                    HStack(spacing: 10) {
                        Image(systemName: "lock").foregroundStyle(Palette.secondary).frame(width: 22)
                        SecureField("onboarding.password", text: $password)
                            .textContentType(.password)
                            .focused($focus, equals: .password)
                            .submitLabel(.go)
                            .onSubmit(signIn)
                            .accessibilityIdentifier("password")
                    }
                    .signInFieldStyle(focused: focus == .password)
                } else {
                    InlineCodeField(entry: entry, canSend: entry.canSend(to: account), focus: $focus, send: sendCode, complete: signIn)
                }
            }
            .modifier(Shake(shakes: shakeSecond))
            HStack(alignment: .firstTextBaseline, spacing: 12) {
                Group {
                    if let error {
                        Text(error).foregroundStyle(.red)
                    } else if entry.sent && !usePassword {
                        Text(entry.sentNote(for: account)).foregroundStyle(Palette.secondary)
                    } else {
                        Text(usePassword ? "onboarding.register" : "onboarding.autoRegister").foregroundStyle(Palette.secondary)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .fixedSize(horizontal: false, vertical: true)
                Button(usePassword ? "onboarding.useCodeLink" : "onboarding.usePasswordLink") {
                    usePassword.toggle()
                    error = nil
                    focus = nil
                }
                .fontWeight(.semibold)
                .foregroundStyle(Palette.brandText)
                .accessibilityIdentifier("loginMode")
            }
            .font(.footnote)
            // Always looks tappable: with something missing it shakes that field instead.
            Button(action: signIn) {
                HStack(spacing: 8) {
                    if busy { ProgressView().tint(.white) }
                    Text("onboarding.signIn").font(.headline)
                    if !busy { Image(systemName: "arrow.right").font(.subheadline.weight(.semibold)) }
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 15)
                .background(
                    LinearGradient(colors: [Palette.brandButtonTop, Palette.brandButtonBottom], startPoint: .top, endPoint: .bottom),
                    in: RoundedRectangle(cornerRadius: 14, style: .continuous)
                )
                .foregroundStyle(.white)
                .shadow(color: Palette.brand.opacity(0.3), radius: 12, y: 6)
            }
            .buttonStyle(PressDown())
            .disabled(busy)
            .padding(.top, 4)
            .accessibilityIdentifier("signIn")
            Text("onboarding.agreement")
                .font(.caption)
                .foregroundStyle(Palette.secondary)
                .tint(Palette.text)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var divider: some View {
        HStack(spacing: 12) {
            Rectangle().fill(Palette.hairline).frame(height: 1)
            Text("onboarding.or").font(.caption).foregroundStyle(Palette.secondary)
            Rectangle().fill(Palette.hairline).frame(height: 1)
        }
    }

    /// "Use without signing in": the user's own API key or local model.
    private var ownModelRow: some View {
        Button { ownModel = true } label: {
            HStack(spacing: 14) {
                Image(systemName: "slider.horizontal.3")
                    .font(.system(size: 18, weight: .semibold))
                    .frame(width: 40, height: 40)
                    .background(Palette.raised, in: RoundedRectangle(cornerRadius: 11, style: .continuous))
                VStack(alignment: .leading, spacing: 3) {
                    Text("onboarding.ownModel").font(.subheadline.weight(.semibold))
                    Text("onboarding.ownModelBody")
                        .font(.caption)
                        .foregroundStyle(Palette.secondary)
                        .multilineTextAlignment(.leading)
                }
                Spacer(minLength: 4)
                Image(systemName: "chevron.right").font(.footnote.weight(.semibold)).foregroundStyle(Palette.secondary)
            }
            .padding(16)
            .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).stroke(Palette.hairline, lineWidth: 1))
            .contentShape(Rectangle())
        }
        .foregroundStyle(Palette.text)
        .accessibilityIdentifier("ownModel")
    }

    private func sendCode() {
        guard entry.canSend(to: account), target != nil else { return }
        error = nil
        Task {
            let account = account
            if let failure = await entry.send({
                try await ServerBackend.sendLynxceCode(ServerBackend.lynxceCloud, target: account)
            }) {
                error = LynxceBackend.codeMessage(for: failure)
            }
        }
    }

    private func signIn() {
        guard !busy else { return }
        guard canSignIn else {
            // Point at what is missing rather than greying the button out.
            let missing = Self.missingField(account: account, usePassword: usePassword)
            withAnimation(.linear(duration: 0.4)) {
                if missing == .account { shakeAccount += 1 } else { shakeSecond += 1 }
            }
            focus = missing
            return
        }
        busy = true
        error = nil
        Task {
            defer { busy = false }
            do {
                let backend: ChatBackend
                let trimmed = account.trimmingCharacters(in: .whitespaces)
                if usePassword {
                    backend = try await ServerBackend.signInWithLynxce(ServerBackend.lynxceCloud, account: trimmed, password: password)
                    password = ""
                } else {
                    guard target != nil else { return }
                    backend = try await ServerBackend.signInWithLynxceCode(ServerBackend.lynxceCloud, target: trimmed, code: entry.code)
                    entry.code = ""
                    entry.reset()
                }
                await model.use(backend)
            } catch {
                if usePassword {
                    self.error = error.localizedDescription
                } else {
                    self.error = LynxceBackend.codeMessage(for: error)
                    // A rejected code is spent; clear it so a new one can be typed or autofilled.
                    if (error as? APIError)?.status == 401 { entry.code = "" }
                }
            }
        }
    }
}

/// Connect to an Octop Bot web/NAS build.
struct ServerConnectView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @AppStorage("server.lastAddress") private var address = ""
    @FocusState private var addressFocused: Bool
    @FocusState private var accountFocused: Bool
    /// The address the current probe answered for; editing it away starts over.
    @State private var probedAddress: String?
    @State private var probe: ServerBackend.SignInMode?
    @State private var account = ""
    @State private var password = ""
    /// Old local password, asked once when a server set up with one binds its Lynxce owner.
    @State private var legacyPassword = ""
    /// Lynxce owners sign in with a code unless they switch to their password.
    @State private var entry = CodeEntry()
    @State private var lynxcePassword = false
    @State private var busy = false
    @State private var error: String?

    private var lynxceCode: Bool { probe != .unsupported && !lynxcePassword }

    private var ready: Bool {
        guard !address.isEmpty else { return false }
        guard let probe else { return true }
        if probe == .unsupported || (probe == .legacy && legacyPassword.isEmpty) { return false }
        return lynxceCode ? LynxceBackend.CodeTarget(account) != nil && entry.isComplete : !password.isEmpty
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("server.address.placeholder", text: $address)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .onChange(of: address) {
                            if address != probedAddress { probe = nil; entry.reset() }
                        }
                        .onSubmit(next)
                        .focused($addressFocused)
                        .accessibilityIdentifier("serverAddress")
                } header: {
                    Text("server.address")
                } footer: {
                    Text("server.address.footer")
                }
                if probe == .unsupported {
                    Section { Text("server.unsupported") }
                } else if let probe {
                    Section {
                        TextField("onboarding.account", text: $account)
                            .textContentType(.username)
                            .keyboardType(.emailAddress)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .focused($accountFocused)
                            .onChange(of: account) { entry.reset() }
                        if lynxceCode {
                            CodeEntryRow(entry: entry, canSend: entry.canSend(to: account), boxed: false, send: sendCode, complete: next)
                        } else {
                            SecureField("onboarding.password", text: $password)
                                .textContentType(.password)
                                .onSubmit(next)
                                .accessibilityIdentifier("serverPassword")
                        }
                        // The server's old local password comes after the Lynxce account it is being bound to.
                        if probe == .legacy {
                            SecureField("server.legacyPassword", text: $legacyPassword)
                                .textContentType(.password)
                                .accessibilityIdentifier("serverLegacyPassword")
                        }
                        Button(lynxcePassword ? "onboarding.useCode" : "onboarding.usePassword") {
                            lynxcePassword.toggle()
                            error = nil
                        }
                        .foregroundStyle(Palette.text)
                        .accessibilityIdentifier("serverLoginMode")
                    } header: {
                        // "The account that owns this server" only fits a claimed self-hosted server.
                        Text(probe == .lynxce(claimed: true) ? "server.signIn.lynxce" : "onboarding.lynxce")
                    } footer: {
                        VStack(alignment: .leading, spacing: 6) {
                            if lynxceCode && entry.sent { Text(entry.sentNote(for: account)) }
                            if probe == .lynxce(claimed: false) { Text("server.unclaimed") }
                            if probe == .legacy { Text("server.legacy.footer") }
                        }
                    }
                }
                if let error {
                    Section { Text(error).foregroundStyle(.red) }
                }
            }
            .onAppear { addressFocused = address.isEmpty }
            .navigationTitle("server.title")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("common.cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    if busy {
                        ProgressView()
                    } else {
                        Button(probe == nil ? "server.next" : "onboarding.signIn", action: next)
                            .disabled(!ready)
                    }
                }
            }
        }
    }

    private func sendCode() {
        guard let url = ServerBackend.normalize(address), entry.canSend(to: account) else { return }
        error = nil
        Task {
            if let failure = await entry.send({ try await ServerBackend.sendLynxceCode(url, target: account) }) {
                error = failure.localizedDescription
            }
        }
    }

    private func next() {
        guard !busy else { return }
        if probe != nil && !ready { return }
        busy = true
        error = nil
        Task {
            defer { busy = false }
            do {
                guard let url = ServerBackend.normalize(address) else {
                    error = L("server.address.invalid")
                    return
                }
                guard let probe else {
                    let (found, reachable) = try await ServerBackend.probeTryingHTTP(url, typedScheme: address.contains("://"))
                    probedAddress = reachable.absoluteString
                    address = reachable.absoluteString
                    self.probe = found
                    if found == .legacy {
                        // The fields appear in this update; focus the first once it exists.
                        try? await Task.sleep(for: .milliseconds(150))
                        accountFocused = true
                    }
                    return
                }
                let legacy = probe == .legacy ? legacyPassword : nil
                let backend: ServerBackend
                if lynxceCode {
                    backend = try await ServerBackend.signInWithLynxceCode(url, target: account, code: entry.code, localPassword: legacy)
                    entry.code = ""
                    entry.reset()
                } else {
                    backend = try await ServerBackend.signInWithLynxce(url, account: account, password: password, localPassword: legacy)
                }
                await model.use(backend)
                dismiss()
            } catch {
                // The server already localizes its messages; a rejected code is cleared for a new one.
                self.error = error.localizedDescription
                if lynxceCode && (error as? APIError)?.status == 401 { entry.code = "" }
            }
        }
    }
}

/// The code half of a Lynxce code sign-in, shared by the Lynxce and server sign-in forms:
/// the typed code, the request in flight and the 60 s resend countdown.
@Observable
final class CodeEntry {
    var code = ""
    private(set) var sending = false
    private(set) var sent = false
    /// Seconds until another code may be requested.
    private(set) var countdown = 0
    /// Bumped on each successful send so the code field can take focus.
    private(set) var sends = 0
    private var timer: Task<Void, Never>?

    var isComplete: Bool { LynxceBackend.isCode(code) }

    func canSend(to account: String) -> Bool {
        !sending && countdown == 0 && LynxceBackend.CodeTarget(account) != nil
    }

    func sentNote(for account: String) -> LocalizedStringKey {
        LynxceBackend.CodeTarget(account)?.isEmail == true ? "onboarding.codeSent.email" : "onboarding.codeSent.phone"
    }

    /// A new phone number, email or server gets its own code right away.
    func reset() {
        timer?.cancel()
        countdown = 0
        sent = false
    }

    /// Run the send request and start the countdown when it succeeds. Returns the failure, if any.
    func send(_ request: () async throws -> Void) async -> Error? {
        sending = true
        defer { sending = false }
        do {
            try await request()
        } catch {
            return error
        }
        sent = true
        sends += 1
        timer?.cancel()
        countdown = 60
        timer = Task { [weak self] in
            while let self, self.countdown > 0 {
                try? await Task.sleep(for: .seconds(1))
                if Task.isCancelled { return }
                self.countdown -= 1
            }
        }
        return nil
    }
}

/// Numeric code field (SMS autofill, submits at 6 digits) beside a send / countdown / resend button.
/// `boxed` draws the onboarding card style; without it the row sits in a `Form`.
struct CodeEntryRow: View {
    @Bindable var entry: CodeEntry
    var canSend: Bool
    var boxed = true
    /// Inside the start page's account card: fields on the page background.
    var card = false
    var send: () -> Void
    var complete: () -> Void
    @FocusState private var focused: Bool

    var body: some View {
        HStack(spacing: 10) {
            field
            Button(action: send) {
                Group {
                    if entry.sending {
                        ProgressView()
                    } else if entry.countdown > 0 {
                        Text(L("onboarding.resendIn %lld", entry.countdown)).monospacedDigit()
                    } else {
                        Text(entry.sent ? "onboarding.resendCode" : "onboarding.sendCode")
                    }
                }
                .font(.subheadline.weight(.medium))
                .lineLimit(1)
                .frame(minWidth: 92, maxHeight: boxed ? .infinity : nil, alignment: boxed ? .center : .trailing)
                .padding(.horizontal, boxed ? 14 : 0)
                .background(boxed ? (card ? Palette.background : Palette.surface) : .clear, in: RoundedRectangle(cornerRadius: card ? 12 : 16, style: .continuous))
                .foregroundStyle(canSend ? Palette.text : Palette.secondary)
            }
            .buttonStyle(.borderless)
            .disabled(!canSend)
            .accessibilityIdentifier("sendCode")
        }
        .fixedSize(horizontal: false, vertical: true)
        // In a Form the separator would otherwise start at the button's text.
        .alignmentGuide(.listRowSeparatorLeading) { _ in 0 }
    }

    @ViewBuilder private var field: some View {
        let input = TextField("onboarding.code", text: $entry.code)
            .keyboardType(.numberPad)
            .textContentType(.oneTimeCode)
            .focused($focused)
            .onChange(of: entry.code) { _, value in
                let digits = String(value.filter { $0.isASCII && $0.isNumber }.prefix(6))
                if digits != value {
                    entry.code = digits
                } else if digits.count == 6 {
                    complete()
                }
            }
            .onChange(of: entry.sends) { focused = true }
            .accessibilityIdentifier("code")
        if card { input.cardFieldStyle() } else if boxed { input.fieldStyle() } else { input }
    }
}

extension View {
    /// A field inside the start page's account card.
    func cardFieldStyle() -> some View {
        padding(.horizontal, 14)
            .padding(.vertical, 13)
            .background(Palette.background, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(Palette.hairline, lineWidth: 1))
    }

    func fieldStyle() -> some View {
        padding(.horizontal, 16)
            .padding(.vertical, 14)
            .background(Palette.surface, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
    }
}

/// The rose stage behind the sign-in banner (the desktop's left panel): light and dark versions.
struct StageBackground: View {
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        let dark = scheme == .dark
        ZStack {
            LinearGradient(
                colors: dark
                    ? [Color(hex: 0x6A2337), Color(hex: 0x4A1A2C), Color(hex: 0x24111D)]
                    : [Color(hex: 0xFF8E9F), Color(hex: 0xE85D75), Color(hex: 0xB3305A)],
                startPoint: .topLeading, endPoint: .bottomTrailing
            )
            RadialGradient(
                colors: [Color(red: 1, green: dark ? 0.59 : 0.84, blue: dark ? 0.47 : 0.67).opacity(dark ? 0.28 : 0.55), .clear],
                center: UnitPoint(x: 0.85, y: 0.05), startRadius: 0, endRadius: 220
            )
            RadialGradient(
                colors: [Color(red: dark ? 0.35 : 0.47, green: dark ? 0.12 : 0.16, blue: dark ? 0.43 : 0.47).opacity(dark ? 0.6 : 0.5), .clear],
                center: UnitPoint(x: 0, y: 1), startRadius: 0, endRadius: 220
            )
        }
    }
}

private extension Color {
    init(hex: UInt32) {
        self.init(red: Double((hex >> 16) & 0xFF) / 255, green: Double((hex >> 8) & 0xFF) / 255, blue: Double(hex & 0xFF) / 255)
    }
}

/// A quick side-to-side shake when the field it wraps is missing; animate `shakes` up by one.
struct Shake: GeometryEffect {
    var shakes: CGFloat
    var animatableData: CGFloat {
        get { shakes }
        set { shakes = newValue }
    }

    func effectValue(size: CGSize) -> ProjectionTransform {
        ProjectionTransform(CGAffineTransform(translationX: 7 * sin(shakes * .pi * 4), y: 0))
    }
}

/// The primary button sinks a little while pressed.
struct PressDown: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? 0.98 : 1)
            .brightness(configuration.isPressed ? -0.04 : 0)
            .animation(.snappy(duration: 0.15), value: configuration.isPressed)
    }
}

/// The 6-digit code with "Get code" (then the countdown) inside the field, as on the desktop.
struct InlineCodeField<Field: Hashable>: View {
    @Bindable var entry: CodeEntry
    var canSend: Bool
    var focus: FocusState<Field?>.Binding
    let field: Field
    var send: () -> Void
    var complete: () -> Void

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "checkmark.shield").foregroundStyle(Palette.secondary).frame(width: 22)
            TextField("onboarding.code", text: $entry.code)
                .keyboardType(.numberPad)
                .textContentType(.oneTimeCode)
                .focused(focus, equals: field)
                .onChange(of: entry.code) { _, value in
                    let digits = String(value.filter { $0.isASCII && $0.isNumber }.prefix(6))
                    if digits != value {
                        entry.code = digits
                    } else if digits.count == 6 {
                        complete()
                    }
                }
                .onChange(of: entry.sends) { focus.wrappedValue = field }
                .accessibilityIdentifier("code")
            Button(action: send) {
                Group {
                    if entry.sending {
                        ProgressView()
                    } else if entry.countdown > 0 {
                        Text(L("onboarding.resendIn %lld", entry.countdown)).monospacedDigit()
                    } else {
                        Text(entry.sent ? "onboarding.resendCode" : "onboarding.sendCode")
                    }
                }
                .font(.subheadline.weight(.semibold))
                .lineLimit(1)
                .foregroundStyle(canSend ? Palette.brandText : Palette.secondary)
            }
            .buttonStyle(.borderless)
            .disabled(!canSend)
            .accessibilityIdentifier("sendCode")
        }
        .signInFieldStyle(focused: focus.wrappedValue == field)
    }
}

extension InlineCodeField where Field == OnboardingView.Field {
    init(entry: CodeEntry, canSend: Bool, focus: FocusState<Field?>.Binding, send: @escaping () -> Void, complete: @escaping () -> Void) {
        self.init(entry: entry, canSend: canSend, focus: focus, field: .code, send: send, complete: complete)
    }
}

extension View {
    /// The sign-in page's fields: page background, hairline border, a rose ring while focused.
    func signInFieldStyle(focused: Bool) -> some View {
        padding(.horizontal, 14)
            .padding(.vertical, 14)
            .background(Palette.background, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .stroke(focused ? Palette.brand : Palette.hairline, lineWidth: focused ? 1.5 : 1)
            )
            .background(
                RoundedRectangle(cornerRadius: 17, style: .continuous)
                    .stroke(Palette.brand.opacity(focused ? 0.18 : 0), lineWidth: 6)
            )
            .animation(.snappy(duration: 0.15), value: focused)
    }
}
