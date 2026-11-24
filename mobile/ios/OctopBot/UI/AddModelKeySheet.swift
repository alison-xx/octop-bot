import SwiftUI

/// Add one of the user's own vendor API keys: pick a company, then its plan and the key, then the
/// model to chat on once the vendor accepts the key.
struct AddModelKeySheet: View {
    @Environment(\.dismiss) private var dismiss
    let store: ModelKeyStore
    /// Opened from a vendor tile: start at the key step for that company.
    var company: VendorCompany?
    /// A key was added or a model chosen.
    var onChanged: (OwnKeyList) -> Void
    /// A model was chosen (the start page enters the app then).
    var onUsed: (() -> Void)?

    private enum Step { case pick, key, done }

    @State private var catalog: VendorCatalog?
    @State private var loadError: String?
    @State private var step: Step = .pick
    @State private var more = false
    @State private var chosen: VendorCompany?
    @State private var planId = ""
    @State private var apiKey = ""
    @State private var showKey = false
    @State private var baseURL = ""
    @State private var label = ""
    @State private var busy = false
    @State private var error: String?
    @State private var added: OwnKey?
    @State private var modelId = ""
    @FocusState private var keyFocused: Bool

    private var custom: Bool { chosen?.id == VendorCompany.custom }
    private var plan: KeyVendor? { chosen?.plans.first { $0.id == planId } }
    private var canSave: Bool {
        !apiKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && (!custom || !baseURL.trimmingCharacters(in: .whitespaces).isEmpty)
    }

    var body: some View {
        NavigationStack {
            Group {
                switch step {
                case .pick: pick
                case .key: keyForm
                case .done: done
                }
            }
            .navigationTitle(title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { toolbar }
        }
        .presentationDragIndicator(.visible)
        .interactiveDismissDisabled(busy)
        .task {
            if let company {
                choose(company)
            }
            await loadCatalog()
        }
    }

    private var title: String {
        switch step {
        case .pick: return L("models.add.title")
        case .done: return L("models.add.doneTitle")
        case .key: return custom ? L("models.add.custom") : L("models.add.vendorTitle %@", chosen?.name ?? "")
        }
    }

    @ToolbarContentBuilder private var toolbar: some ToolbarContent {
        ToolbarItem(placement: .cancellationAction) {
            if step == .key && company == nil {
                Button {
                    step = .pick
                    error = nil
                } label: {
                    Label("models.add.back", systemImage: "chevron.left").labelStyle(.titleAndIcon)
                }
            } else if step != .done {
                Button("common.cancel") { dismiss() }
            }
        }
        if step == .key {
            ToolbarItem(placement: .confirmationAction) {
                if busy {
                    ProgressView()
                } else {
                    Button("models.add.verify", action: save)
                        .fontWeight(.semibold)
                        .disabled(!canSave)
                        .accessibilityIdentifier("verifyKey")
                }
            }
        }
    }

    // MARK: Pick a company

    private var companies: [VendorCompany] { VendorCompany.group(catalog?.vendors ?? []) }

    @ViewBuilder private var pick: some View {
        if let loadError {
            VStack(spacing: 12) {
                Text(loadError).foregroundStyle(.red).multilineTextAlignment(.center)
                Button("common.retry") { Task { await loadCatalog() } }
            }
            .padding()
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if let catalog {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    Text(store.onPhone ? "models.add.hintPhone" : "models.add.hintCloud")
                        .font(.subheadline)
                        .foregroundStyle(Palette.secondary)
                    VendorGrid(companies: companies.filter(\.isFeatured), choose: choose)
                    let others = companies.filter { !$0.isFeatured }
                    if !others.isEmpty {
                        if more {
                            VendorGrid(companies: others, choose: choose)
                        } else {
                            Button(L("models.add.more %lld", others.count)) { withAnimation(.snappy) { more = true } }
                                .font(.subheadline.weight(.medium))
                                .foregroundStyle(Palette.text)
                                .accessibilityIdentifier("moreVendors")
                        }
                    }
                    if catalog.customAllowed {
                        Button { choose(VendorCompany(id: VendorCompany.custom, plans: [])) } label: {
                            HStack(spacing: 12) {
                                VendorLogo(company: VendorCompany.custom, size: 30)
                                Text("models.add.custom").font(.subheadline.weight(.medium))
                                Spacer()
                                Image(systemName: "chevron.right").font(.footnote.weight(.semibold)).foregroundStyle(Palette.secondary)
                            }
                            .padding(14)
                            .overlay(RoundedRectangle(cornerRadius: 14).strokeBorder(Palette.hairline, style: StrokeStyle(lineWidth: 1, dash: [4, 3])))
                        }
                        .foregroundStyle(Palette.text)
                        .accessibilityIdentifier("customVendor")
                    }
                }
                .padding(20)
            }
        } else {
            ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }

    private func choose(_ next: VendorCompany) {
        chosen = next
        planId = next.plans.first?.id ?? ""
        apiKey = ""
        baseURL = ""
        label = ""
        error = nil
        step = .key
        keyFocused = true
    }

    // MARK: The key

    private var keyForm: some View {
        Form {
            if let chosen, !custom, chosen.plans.count > 1 {
                Section {
                    Picker("models.add.plan", selection: $planId) {
                        ForEach(chosen.plans) { plan in Text(verbatim: plan.name).tag(plan.id) }
                    }
                    .accessibilityIdentifier("plan")
                }
            }
            if custom {
                Section("models.add.baseUrl") {
                    TextField(text: $baseURL, prompt: Text(verbatim: "https://api.example.com/v1")) { Text("models.add.baseUrl") }
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                }
                Section("models.add.name") {
                    TextField("models.add.name", text: $label)
                }
            }
            Section {
                HStack(spacing: 8) {
                    Group {
                        if showKey {
                            TextField(text: $apiKey, prompt: Text(verbatim: keyPrompt)) { Text(verbatim: "API Key") }
                        } else {
                            SecureField(text: $apiKey, prompt: Text(verbatim: keyPrompt)) { Text(verbatim: "API Key") }
                        }
                    }
                    // Not a password: keep iOS from offering to save it to Passwords.
                    .textContentType(.oneTimeCode)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .focused($keyFocused)
                    .submitLabel(.done)
                    .onSubmit(save)
                    .onChange(of: apiKey) { error = nil }
                    .accessibilityIdentifier("apiKey")
                    Button {
                        showKey.toggle()
                    } label: {
                        Image(systemName: showKey ? "eye.slash" : "eye").foregroundStyle(Palette.secondary)
                    }
                    .buttonStyle(.borderless)
                    .accessibilityLabel(Text(showKey ? "models.add.hideKey" : "models.add.showKey"))
                }
            } header: {
                Text(verbatim: "API Key")
            } footer: {
                VStack(alignment: .leading, spacing: 6) {
                    Text(store.onPhone ? "models.add.keptPhone" : "models.add.keptCloud")
                    if !custom, let plan {
                        Text(verbatim: "\(L("models.add.endpoint")) \(plan.baseURL)").lineLimit(2)
                        if let docs = plan.docs, let url = URL(string: docs), !docs.isEmpty {
                            Link(destination: url) {
                                Label("models.add.getKey", systemImage: "arrow.up.right").labelStyle(.titleAndIcon)
                            }
                            .font(.footnote.weight(.semibold))
                        }
                    }
                }
            }
            if let error {
                Section {
                    Label {
                        Text(verbatim: error)
                    } icon: {
                        Image(systemName: "exclamationmark.circle.fill")
                    }
                    .font(.subheadline)
                    .foregroundStyle(.red)
                    .accessibilityIdentifier("keyError")
                }
            }
        }
    }

    private var keyPrompt: String {
        let prefix = plan?.apiKeyPrefix ?? ""
        return prefix.isEmpty ? L("models.add.keyPlaceholder") : prefix + "…"
    }

    private func save() {
        guard !busy, canSave, let chosen else { return }
        busy = true
        error = nil
        keyFocused = false
        let request = custom
            ? NewOwnKey(vendor: VendorCompany.custom, apiKey: apiKey.trimmingCharacters(in: .whitespacesAndNewlines), name: label, baseURL: baseURL.trimmingCharacters(in: .whitespaces))
            : NewOwnKey(vendor: planId.isEmpty ? (chosen.plans.first?.id ?? "") : planId, apiKey: apiKey.trimmingCharacters(in: .whitespacesAndNewlines))
        Task {
            defer { busy = false }
            do {
                let key = try await store.add(request)
                // Empty the secure field before it leaves the screen, or iOS offers to save the key as a password.
                apiKey = ""
                showKey = false
                try? await Task.sleep(for: .milliseconds(120))
                added = key
                modelId = key.models.first?.id ?? ""
                step = .done
                Haptics.success()
                if let list = try? await store.list() { onChanged(list) }
            } catch {
                self.error = error.localizedDescription
            }
        }
    }

    // MARK: Choose the model

    private var done: some View {
        Form {
            Section {
                Label {
                    Text(L("models.add.found %lld", added?.models.count ?? 0))
                } icon: {
                    Image(systemName: "checkmark.circle.fill").foregroundStyle(.green)
                }
                .font(.subheadline.weight(.medium))
                .accessibilityIdentifier("keyAdded")
            }
            if let added, !added.models.isEmpty {
                Section("models.add.chooseModel") {
                    ForEach(added.models) { choice in
                        Button {
                            modelId = choice.id
                        } label: {
                            HStack {
                                Text(verbatim: choice.label).foregroundStyle(Palette.text)
                                Spacer()
                                if modelId == choice.id {
                                    Image(systemName: "checkmark").font(.body.weight(.semibold)).foregroundStyle(Palette.text)
                                }
                            }
                        }
                    }
                }
            }
            if let error {
                Section { Text(verbatim: error).foregroundStyle(.red) }
            }
            Section {
                Button(action: useModel) {
                    HStack {
                        Spacer()
                        if busy { ProgressView().tint(Palette.background) } else { Text("models.add.useModel").font(.headline) }
                        Spacer()
                    }
                    .padding(.vertical, 4)
                }
                .listRowBackground(Palette.text)
                .foregroundStyle(Palette.background)
                .disabled(modelId.isEmpty || busy)
                .accessibilityIdentifier("useModel")
            }
            if onUsed == nil {
                Section {
                    Button("models.add.later") { dismiss() }
                        .frame(maxWidth: .infinity)
                        .foregroundStyle(Palette.text)
                }
            }
        }
    }

    private func useModel() {
        guard let added, !modelId.isEmpty, !busy else { return }
        busy = true
        error = nil
        Task {
            defer { busy = false }
            do {
                onChanged(try await store.use(added.id, model: modelId))
                Haptics.success()
                dismiss()
                onUsed?()
            } catch {
                self.error = error.localizedDescription
            }
        }
    }

    private func loadCatalog() async {
        loadError = nil
        do {
            catalog = try await store.vendors()
            // A tile picked before the server's list arrived: use that company's plans from it.
            if let current = chosen, current.id != VendorCompany.custom,
               let fresh = companies.first(where: { $0.id == current.id }) {
                chosen = fresh
                if !fresh.plans.contains(where: { $0.id == planId }) { planId = fresh.plans.first?.id ?? "" }
            }
        } catch {
            loadError = error.localizedDescription
        }
    }
}

/// Company tiles, three to a row.
struct VendorGrid: View {
    var companies: [VendorCompany]
    var choose: (VendorCompany) -> Void

    var body: some View {
        LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 10), count: 3), spacing: 10) {
            ForEach(companies) { company in
                Button { choose(company) } label: {
                    VStack(spacing: 8) {
                        VendorLogo(company: company.id, size: 34)
                        Text(verbatim: company.name)
                            .font(.footnote.weight(.medium))
                            .lineLimit(1)
                            .minimumScaleFactor(0.8)
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 14)
                    .padding(.horizontal, 6)
                    .background(Palette.surface, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                }
                .foregroundStyle(Palette.text)
                .accessibilityIdentifier("vendor-\(company.id)")
            }
        }
    }
}

/// Connect the Ollama or LM Studio running on a computer on the same network.
struct LocalModelSheet: View {
    @Environment(\.dismiss) private var dismiss
    @AppStorage("models.local.lastAddress") private var address = ""
    var onUsed: (LocalServer) -> Void
    @State private var busy = false
    @State private var error: String?
    @State private var found: LocalServer?
    @State private var modelId = ""
    @FocusState private var focused: Bool

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField(text: $address, prompt: Text(verbatim: "192.168.1.8:11434")) { Text("models.local.address") }
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .onSubmit(connect)
                        .onChange(of: address) { found = nil; error = nil }
                        .focused($focused)
                        .accessibilityIdentifier("localAddress")
                } header: {
                    Text("models.local.address")
                } footer: {
                    Text("models.local.addressFooter")
                }
                if let error {
                    Section { Text(verbatim: error).foregroundStyle(.red) }
                }
                if let found {
                    Section("models.add.chooseModel") {
                        ForEach(found.models) { choice in
                            Button { modelId = choice.id } label: {
                                HStack {
                                    Text(verbatim: choice.label).foregroundStyle(Palette.text)
                                    Spacer()
                                    if modelId == choice.id { Image(systemName: "checkmark").font(.body.weight(.semibold)) }
                                }
                            }
                        }
                    }
                }
            }
            .onAppear { focused = true }
            .navigationTitle("models.local.addTitle")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("common.cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    if busy {
                        ProgressView()
                    } else if let found {
                        Button("models.local.use") {
                            PhoneModels.shared.useLocal(found.id, model: modelId)
                            dismiss()
                            onUsed(found)
                        }
                        .fontWeight(.semibold)
                        .disabled(modelId.isEmpty)
                    } else {
                        Button("models.local.connect", action: connect)
                            .fontWeight(.semibold)
                            .disabled(address.trimmingCharacters(in: .whitespaces).isEmpty)
                    }
                }
            }
        }
    }

    private func connect() {
        guard !busy else { return }
        busy = true
        error = nil
        Task {
            defer { busy = false }
            do {
                let server = try await PhoneModels.shared.addLocal(address: address)
                found = server
                modelId = server.models.first?.id ?? ""
            } catch {
                self.error = error.localizedDescription
            }
        }
    }
}
