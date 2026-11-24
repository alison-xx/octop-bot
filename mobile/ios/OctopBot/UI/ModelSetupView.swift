import SwiftUI

/// "Use without signing in": choose the model Bots reply with — the user's own vendor API key, or
/// an Ollama / LM Studio on their network. Picking one starts the app in phone-only use.
struct ModelSetupView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var phone = PhoneModels.shared
    @State private var company: VendorCompany?
    @State private var addingLocal = false
    @State private var more = false
    @State private var starting = false

    private var companies: [VendorCompany] { VendorCompany.group(VendorCatalog.bundled.vendors) }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 26) {
                header
                keysSection
                localSection
                lynxceNote
            }
            .padding(.horizontal, 20)
            .padding(.top, 8)
            .padding(.bottom, 24)
            .frame(maxWidth: 560)
            .frame(maxWidth: .infinity)
        }
        .background(Palette.background.ignoresSafeArea())
        .safeAreaInset(edge: .bottom) { startBar }
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .principal) {
                Text("models.setup.mode").font(.footnote).foregroundStyle(Palette.secondary)
            }
        }
        .sheet(item: $company) { company in
            AddModelKeySheet(store: phone, company: company, onChanged: { _ in }, onUsed: start)
        }
        .sheet(isPresented: $addingLocal) {
            LocalModelSheet { _ in start() }
        }
    }

    private var header: some View {
        HStack(alignment: .bottom, spacing: 12) {
            VStack(alignment: .leading, spacing: 8) {
                Text("models.setup.title")
                    .font(.system(size: 28, weight: .bold))
                    .foregroundStyle(Palette.text)
                Text("models.setup.body")
                    .font(.subheadline)
                    .foregroundStyle(Palette.secondary)
            }
            Spacer(minLength: 0)
            CharacterView(look: .chief, size: 64)
        }
    }

    private var keysSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            VStack(alignment: .leading, spacing: 3) {
                Text("models.setup.keys").font(.headline)
                Text("models.setup.keysNote").font(.caption).foregroundStyle(Palette.secondary)
            }
            VendorGrid(companies: companies.filter(\.isFeatured)) { company = $0 }
            let others = companies.filter { !$0.isFeatured }
            if more {
                VendorGrid(companies: others) { company = $0 }
            }
            HStack(spacing: 10) {
                if !more && !others.isEmpty {
                    Button(L("models.add.more %lld", others.count)) { withAnimation(.snappy) { more = true } }
                        .buttonStyle(PillButtonStyle())
                        .accessibilityIdentifier("moreVendors")
                }
                Button { company = VendorCompany(id: VendorCompany.custom, plans: []) } label: {
                    Label("models.add.customShort", systemImage: "plus")
                }
                .buttonStyle(PillButtonStyle())
                .accessibilityIdentifier("customVendor")
            }
        }
    }

    private var localSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("models.local.title").font(.headline)
            Button { addingLocal = true } label: {
                HStack(spacing: 12) {
                    VendorLogo(company: "ollama", size: 36)
                    VStack(alignment: .leading, spacing: 3) {
                        Text("models.setup.local").font(.subheadline.weight(.semibold)).foregroundStyle(Palette.text)
                            .multilineTextAlignment(.leading)
                        Text("models.setup.localBody").font(.caption).foregroundStyle(Palette.secondary)
                            .multilineTextAlignment(.leading)
                    }
                    Spacer(minLength: 8)
                    Image(systemName: "chevron.right").font(.footnote.weight(.semibold)).foregroundStyle(Palette.secondary)
                }
                .padding(14)
                .background(Palette.surface, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            }
            .accessibilityIdentifier("addLocal")
        }
    }

    private var lynxceNote: some View {
        HStack(alignment: .top, spacing: 10) {
            VendorLogo(company: "lynxce", size: 22)
            VStack(alignment: .leading, spacing: 6) {
                Text("models.setup.lynxce").font(.footnote).foregroundStyle(Palette.secondary)
                Button("models.lynxce.signIn") { dismiss() }
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(Palette.text)
                    .accessibilityIdentifier("backToSignIn")
            }
        }
    }

    /// A model set up earlier (this visit or a previous one): start with it.
    @ViewBuilder private var startBar: some View {
        if let current = phone.current, phone.hasModel {
            Button(action: start) {
                HStack {
                    if starting { ProgressView().tint(Palette.background) }
                    Text(L("models.setup.start %@", current.model)).font(.headline).lineLimit(1)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14)
                .background(Palette.text, in: Capsule())
                .foregroundStyle(Palette.background)
            }
            .disabled(starting)
            .padding(.horizontal, 20)
            .padding(.vertical, 10)
            .background(.bar)
            .accessibilityIdentifier("startWithModel")
        }
    }

    private func start() {
        guard !starting, phone.hasModel else { return }
        starting = true
        Haptics.success()
        Task {
            await model.use(DeviceBackend.start())
            starting = false
        }
    }
}
