import SwiftUI

/// First screen: sign in with a Lynxce account, or connect a self-hosted server.
struct OnboardingView: View {
    @Environment(AppModel.self) private var model
    @State private var account = ""
    @State private var password = ""
    @State private var busy = false
    @State private var error: String?
    @State private var showServer = false
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

    private var form: some View {
        VStack(spacing: 12) {
            Text("onboarding.lynxce")
                .font(.headline)
                .frame(maxWidth: .infinity, alignment: .leading)
            TextField("onboarding.account", text: $account)
                .textContentType(.username)
                .keyboardType(.emailAddress)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .focused($focus, equals: .account)
                .submitLabel(.next)
                .onSubmit { focus = .password }
                .fieldStyle()
                .accessibilityIdentifier("account")
            SecureField("onboarding.password", text: $password)
                .textContentType(.password)
                .focused($focus, equals: .password)
                .submitLabel(.go)
                .onSubmit(signIn)
                .fieldStyle()
                .accessibilityIdentifier("password")
            if let error {
                Text(error)
                    .font(.footnote)
                    .foregroundStyle(.red)
                    .frame(maxWidth: .infinity, alignment: .leading)
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
            .disabled(busy || account.isEmpty || password.count < 8)
            .opacity(account.isEmpty || password.count < 8 ? 0.5 : 1)
            .accessibilityIdentifier("signIn")
            Link("onboarding.register", destination: URL(string: "https://www.lynxce.cn")!)
                .font(.footnote)
                .foregroundStyle(Palette.secondary)
        }
    }

    private func signIn() {
        guard !busy, !account.isEmpty, password.count >= 8 else { return }
        busy = true
        error = nil
        Task {
            defer { busy = false }
            do {
                let backend = try await LynxceBackend.signIn(account: account.trimmingCharacters(in: .whitespaces), password: password)
                password = ""
                await model.use(backend)
            } catch {
                self.error = error.localizedDescription
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
    @FocusState private var passwordFocused: Bool
    /// The address the current probe answered for; editing it away starts over.
    @State private var probedAddress: String?
    @State private var probe: ServerBackend.SignInMode?
    @State private var account = ""
    @State private var username = ""
    @State private var password = ""
    @State private var mfaToken: String?
    @State private var code = ""
    @State private var busy = false
    @State private var error: String?

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("server.address.placeholder", text: $address)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .onChange(of: address) {
                            if address != probedAddress { probe = nil; mfaToken = nil }
                        }
                        .onSubmit(next)
                        .focused($addressFocused)
                        .accessibilityIdentifier("serverAddress")
                } header: {
                    Text("server.address")
                } footer: {
                    Text("server.address.footer")
                }
                if let probe {
                    Section {
                        switch probe {
                        case .lynxce:
                            TextField("onboarding.account", text: $account)
                                .textContentType(.username)
                                .keyboardType(.emailAddress)
                                .textInputAutocapitalization(.never)
                                .autocorrectionDisabled()
                        case .password:
                            TextField("server.username", text: $username)
                                .textContentType(.username)
                                .textInputAutocapitalization(.never)
                                .autocorrectionDisabled()
                        case .localPassword:
                            EmptyView()
                        }
                        SecureField("onboarding.password", text: $password)
                            .textContentType(.password)
                            .onSubmit(next)
                            .focused($passwordFocused)
                            .accessibilityIdentifier("serverPassword")
                        if mfaToken != nil {
                            TextField("server.mfa", text: $code)
                                .keyboardType(.numberPad)
                                .textContentType(.oneTimeCode)
                        }
                    } header: {
                        switch probe {
                        case .lynxce: Text("server.signIn.lynxce")
                        case .localPassword: Text("server.signIn.local")
                        case .password: Text("server.signIn.password")
                        }
                    } footer: {
                        if probe == .lynxce(claimed: false) { Text("server.unclaimed") }
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
                            .disabled(address.isEmpty || (probe != nil && password.isEmpty))
                    }
                }
            }
        }
    }

    private func next() {
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
                    if found == .localPassword {
                        // The field appears in this update; focus it once it exists.
                        try? await Task.sleep(for: .milliseconds(150))
                        passwordFocused = true
                    }
                    return
                }
                let backend: ServerBackend
                if let mfaToken {
                    backend = try await ServerBackend.verifyMFA(url, token: mfaToken, code: code)
                } else if case .lynxce = probe {
                    backend = try await ServerBackend.signInWithLynxce(url, account: account, password: password)
                } else {
                    let name = probe == .localPassword ? "local" : username.trimmingCharacters(in: .whitespaces)
                    switch try await ServerBackend.signIn(url, username: name, password: password) {
                    case .signedIn(let signedIn): backend = signedIn
                    case .mfa(let token):
                        mfaToken = token
                        return
                    }
                }
                await model.use(backend)
                dismiss()
            } catch {
                self.error = error.localizedDescription
            }
        }
    }
}

extension View {
    func fieldStyle() -> some View {
        padding(.horizontal, 16)
            .padding(.vertical, 14)
            .background(Palette.surface, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
    }
}
