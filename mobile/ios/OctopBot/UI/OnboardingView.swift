import SwiftUI

/// First screen: sign in with a Lynxce account, or connect a self-hosted server.
struct OnboardingView: View {
    @Environment(AppModel.self) private var model
    @State private var account = ""
    @State private var password = ""
    @State private var entry = CodeEntry()
    @State private var usePassword = false
    @State private var busy = false
    @State private var error: String?
    @State private var showServer = false
    /// Octop Bot cloud answered: a Lynxce sign-in lands there (Bots, groups and schedules in the
    /// cloud). Until it is up, Lynxce sign-in talks to Lynxce directly.
    @State private var cloud: Bool?
    /// The cloud check got no answer (even on a slower retry), so this sign-in goes to Lynxce directly.
    @State private var cloudUnreachable = false
    @FocusState private var focus: Field?

    enum Field { case account, password }

    private let crowd: [Look] = [
        Look(shape: "acorn", color: "green"), Look(shape: "beacon", color: "cobalt"),
        Look(shape: "wave", color: "sky"), Look(shape: "bunny", color: "tangerine"),
        Look(shape: "cushion", color: "violet"),
    ]

    var body: some View {
        ScrollView {
            VStack(spacing: 28) {
                hero
                form
                Button("onboarding.server") { showServer = true }
                    .buttonStyle(PillButtonStyle())
                    .accessibilityIdentifier("connectServer")
                Text("onboarding.footnote")
                    .font(.footnote)
                    .foregroundStyle(Palette.secondary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 24)
            }
            .padding(.horizontal, 24)
            .padding(.vertical, 32)
            .frame(maxWidth: 520)
            .frame(maxWidth: .infinity)
        }
        .scrollDismissesKeyboard(.interactively)
        .background(Palette.background.ignoresSafeArea())
        .sheet(isPresented: $showServer) { ServerConnectView() }
        .onAppear {
            // "Switch account or server" from Settings lands here with the server sheet open.
            if model.reopenServerSheet {
                model.reopenServerSheet = false
                showServer = true
            }
        }
    }

    private var hero: some View {
        VStack(spacing: 14) {
            ZStack {
                ForEach(Array(crowd.enumerated()), id: \.offset) { index, look in
                    let angle = Double(index) / Double(crowd.count) * 2 * .pi - .pi / 2
                    CharacterView(look: look, size: 46, seed: look.shape)
                        .offset(x: cos(angle) * 128, y: sin(angle) * 92 + 8)
                }
                CharacterView(look: .chief, size: 120, motion: busy ? .working : .idle)
            }
            .frame(height: 250)
            Text("Octop Bot")
                .font(.system(size: 34, weight: .bold, design: .rounded))
                .foregroundStyle(Palette.text)
            Text("onboarding.tagline")
                .font(.body)
                .foregroundStyle(Palette.secondary)
                .multilineTextAlignment(.center)
        }
    }

    private var target: LynxceBackend.CodeTarget? { LynxceBackend.CodeTarget(account) }

    private func useCloud() async -> Bool {
        if let cloud { return cloud }
        let check = await ServerBackend.lynxceCloudAvailable()
        let available = check == .available
        cloud = available
        // Say so rather than switching modes silently on a slow network.
        cloudUnreachable = check == .unreachable
        return available
    }
    private var canSignIn: Bool {
        usePassword ? !account.isEmpty && password.count >= 8 : target != nil && entry.isComplete
    }

    private var form: some View {
        VStack(spacing: 12) {
            if let notice = model.signedOutNotice {
                Text(notice)
                    .font(.footnote)
                    .foregroundStyle(Palette.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            Text("onboarding.lynxce")
                .font(.headline)
                .frame(maxWidth: .infinity, alignment: .leading)
            TextField("onboarding.account", text: $account)
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
                .fieldStyle()
                .accessibilityIdentifier("account")
            if usePassword {
                SecureField("onboarding.password", text: $password)
                    .textContentType(.password)
                    .focused($focus, equals: .password)
                    .submitLabel(.go)
                    .onSubmit(signIn)
                    .fieldStyle()
                    .accessibilityIdentifier("password")
            } else {
                CodeEntryRow(entry: entry, canSend: entry.canSend(to: account), send: sendCode, complete: signIn)
            }
            if let error {
                Text(error)
                    .font(.footnote)
                    .foregroundStyle(.red)
                    .frame(maxWidth: .infinity, alignment: .leading)
            } else if entry.sent && !usePassword {
                Text(entry.sentNote(for: account))
                    .font(.footnote)
                    .foregroundStyle(Palette.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            if cloudUnreachable {
                VStack(alignment: .leading, spacing: 4) {
                    Label("onboarding.cloudUnreachable", systemImage: "icloud.slash")
                    Button("onboarding.cloudRetry") {
                        cloud = nil
                        cloudUnreachable = false
                        entry.reset()
                        error = nil
                    }
                    .fontWeight(.semibold)
                    .foregroundStyle(Palette.text)
                    .disabled(busy)
                }
                .font(.footnote)
                .foregroundStyle(Palette.secondary)
                .frame(maxWidth: .infinity, alignment: .leading)
                .accessibilityIdentifier("cloudUnreachable")
            }
            Button(action: signIn) {
                HStack {
                    if busy { ProgressView().tint(Palette.background) }
                    Text("onboarding.signIn").font(.headline)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14)
                .background(Palette.text, in: Capsule())
                .foregroundStyle(Palette.background)
            }
            .disabled(busy || !canSignIn)
            .opacity(canSignIn ? 1 : 0.5)
            .accessibilityIdentifier("signIn")
            Button(usePassword ? "onboarding.useCode" : "onboarding.usePassword") {
                usePassword.toggle()
                error = nil
                focus = nil
            }
            .font(.subheadline.weight(.medium))
            .foregroundStyle(Palette.text)
            .padding(.top, 2)
            .accessibilityIdentifier("loginMode")
            if usePassword {
                // New accounts have no password: the code sign-in creates them.
                Button("onboarding.register") {
                    usePassword = false
                    error = nil
                }
                .font(.footnote)
                .foregroundStyle(Palette.secondary)
                .accessibilityIdentifier("register")
            } else {
                Text("onboarding.codeHint")
                    .font(.footnote)
                    .foregroundStyle(Palette.secondary)
                    .multilineTextAlignment(.center)
            }
            Text("onboarding.agreement")
                .font(.caption)
                .foregroundStyle(Palette.secondary)
                .tint(Palette.text)
                .multilineTextAlignment(.center)
                .padding(.top, 4)
        }
    }

    private func sendCode() {
        guard entry.canSend(to: account), let target else { return }
        error = nil
        Task {
            let cloud = await useCloud()
            let account = account
            if let failure = await entry.send({
                if cloud {
                    try await ServerBackend.sendLynxceCode(ServerBackend.lynxceCloud, target: account)
                } else {
                    try await LynxceBackend.requestCode(target: target)
                }
            }) {
                error = LynxceBackend.codeMessage(for: failure)
            }
        }
    }

    private func signIn() {
        guard !busy, canSignIn else { return }
        busy = true
        error = nil
        Task {
            defer { busy = false }
            do {
                let backend: ChatBackend
                let cloud = await useCloud()
                let trimmed = account.trimmingCharacters(in: .whitespaces)
                if usePassword {
                    backend = cloud
                        ? try await ServerBackend.signInWithLynxce(ServerBackend.lynxceCloud, account: trimmed, password: password)
                        : try await LynxceBackend.signIn(account: trimmed, password: password)
                    password = ""
                } else {
                    guard let target else { return }
                    backend = cloud
                        ? try await ServerBackend.signInWithLynxceCode(ServerBackend.lynxceCloud, target: trimmed, code: entry.code)
                        : try await LynxceBackend.signIn(target: target, code: entry.code)
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
                .background(boxed ? Palette.surface : .clear, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
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
        if boxed { input.fieldStyle() } else { input }
    }
}

extension View {
    func fieldStyle() -> some View {
        padding(.horizontal, 16)
            .padding(.vertical, 14)
            .background(Palette.surface, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
    }
}
