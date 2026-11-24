import SwiftUI

/// Settings → Models: three groups like the desktop — Lynxce (credits), my API keys (billed by the
/// vendor) and local models (an Ollama or LM Studio on the user's network, phone-only use).
struct ModelSourcesView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var keys: OwnKeyList?
    @State private var loadError: String?
    @State private var actionError: String?
    @State private var busy: String?
    @State private var adding = false
    @State private var addingLocal = false
    @State private var removing: OwnKey?
    @State private var removingLocal: LocalServer?
    @State private var phone = PhoneModels.shared

    private var store: ModelKeyStore? { model.modelKeys }
    private var onPhone: Bool { store?.onPhone == true }
    /// The phone itself calls the model: a key or local server in use here.
    private var phoneSelection: PhoneSelection? { onPhone ? phone.selection : nil }

    var body: some View {
        List {
            Section {
                Text(LocalizedStringKey(model.server.map { !$0.isCloud } == true ? "models.bodyServer" : "models.body"))
                    .font(.subheadline)
                    .foregroundStyle(Palette.secondary)
                    .listRowBackground(Color.clear)
                    .listRowInsets(EdgeInsets(top: 0, leading: 20, bottom: 0, trailing: 20))
            }
            if let server = model.server, !server.isCloud {
                serverSection
            } else {
                lynxceSection
            }
            keysSection
            if onPhone { localSection }
        }
        .navigationTitle("settings.model")
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
        .refreshable { await load() }
        .sheet(isPresented: $adding) {
            if let store {
                AddModelKeySheet(store: store) { list in
                    apply(list)
                }
            }
        }
        .sheet(isPresented: $addingLocal) {
            LocalModelSheet { _ in
                Task { await load() }
            }
        }
        .confirmationDialog(
            Text("models.keys.removeConfirm"),
            isPresented: Binding(get: { removing != nil }, set: { if !$0 { removing = nil } }),
            titleVisibility: .visible,
            presenting: removing
        ) { key in
            Button("models.keys.remove", role: .destructive) { remove(key) }
        }
        .confirmationDialog(
            Text("models.local.removeConfirm"),
            isPresented: Binding(get: { removingLocal != nil }, set: { if !$0 { removingLocal = nil } }),
            titleVisibility: .visible,
            presenting: removingLocal
        ) { server in
            Button("models.keys.remove", role: .destructive) {
                phone.removeLocal(server.id)
                Task { await load() }
            }
        }
    }

    // MARK: Lynxce

    @ViewBuilder private var lynxceSection: some View {
        Section {
            if model.isLynxce {
                lynxceOption(nil, L("settings.model.auto"), detail: L("settings.model.footer"))
                ForEach(model.models) { choice in
                    lynxceOption(choice.id, choice.name, detail: choice.supportsImage ? L("settings.model.vision") : nil)
                }
                creditsLink
            } else if model.isCloud {
                HStack(spacing: 12) {
                    VendorLogo(company: "lynxce", size: 32)
                    VStack(alignment: .leading, spacing: 3) {
                        Text("models.lynxce.title").font(.body.weight(.semibold))
                        Text("models.lynxce.cloud").font(.caption).foregroundStyle(Palette.secondary)
                    }
                    Spacer(minLength: 8)
                    if keys?.inUse == nil { InUseMark(text: L("models.inUse")).fixedSize() }
                }
                .padding(.vertical, 2)
                if keys?.inUse != nil { leaveButton("models.lynxce.use") }
                creditsLink
            } else {
                Button {
                    dismiss()
                    Task { await model.signOut() }
                } label: {
                    HStack(spacing: 12) {
                        VendorLogo(company: "lynxce", size: 32)
                        VStack(alignment: .leading, spacing: 3) {
                            Text("models.lynxce.signIn").font(.body.weight(.semibold)).foregroundStyle(Palette.text)
                            Text("models.lynxce.signInBody").font(.caption).foregroundStyle(Palette.secondary)
                        }
                        Spacer(minLength: 8)
                        Image(systemName: "chevron.right").font(.footnote.weight(.semibold)).foregroundStyle(Palette.secondary)
                    }
                    .padding(.vertical, 2)
                }
                .accessibilityIdentifier("lynxceSignIn")
            }
        } header: {
            SourceHeader(title: "models.lynxce.title", tag: "models.lynxce.billing")
        }
    }

    /// A self-hosted server: its admin's models, or one of my keys.
    private var serverSection: some View {
        Section {
            HStack(spacing: 12) {
                Image(systemName: "server.rack")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(Palette.text)
                    .frame(width: 32, height: 32)
                    .background(Palette.raised, in: RoundedRectangle(cornerRadius: 8, style: .continuous))
                VStack(alignment: .leading, spacing: 3) {
                    Text("models.server.default").font(.body.weight(.semibold))
                    Text("models.server.body").font(.caption).foregroundStyle(Palette.secondary)
                }
                Spacer(minLength: 8)
                if keys?.inUse == nil { InUseMark(text: L("models.inUse")).fixedSize() }
            }
            .padding(.vertical, 2)
            if keys?.inUse != nil { leaveButton("models.server.use") }
        } header: {
            SourceHeader(title: "models.server.title", tag: "models.server.billing")
        }
    }

    /// Stop chatting on my own key (the key is kept).
    private func leaveButton(_ title: LocalizedStringKey) -> some View {
        Button {
            guard let store = store as? ServerModelKeys else { return }
            busy = "leave"
            actionError = nil
            Task {
                defer { busy = nil }
                do {
                    apply(try await store.leave())
                    Haptics.success()
                } catch {
                    actionError = error.localizedDescription
                }
            }
        } label: {
            HStack {
                Text(title).foregroundStyle(Palette.text)
                Spacer()
                if busy == "leave" { ProgressView() }
            }
        }
        .disabled(busy != nil)
        .accessibilityIdentifier("leaveOwnKey")
    }

    private var creditsLink: some View {
        NavigationLink {
            CreditsView()
        } label: {
            LabeledContent {
                BalanceLabel(allowsRetry: false)
            } label: {
                Text(CreditPurchases.title)
            }
        }
    }

    private func lynxceOption(_ id: String?, _ name: String, detail: String?) -> some View {
        Button {
            Haptics.tap()
            phone.useLynxce()
            model.selectedModel = id
        } label: {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(name).foregroundStyle(Palette.text)
                    if let detail { Text(detail).font(.caption).foregroundStyle(Palette.secondary) }
                }
                Spacer()
                if phoneSelection == nil && model.selectedModel == id {
                    Image(systemName: "checkmark").font(.body.weight(.semibold)).foregroundStyle(Palette.text)
                }
            }
        }
    }

    // MARK: My API keys

    @ViewBuilder private var keysSection: some View {
        Section {
            if let loadError {
                VStack(alignment: .leading, spacing: 8) {
                    Text(loadError).font(.footnote).foregroundStyle(.red)
                    Button("common.retry") { Task { await load() } }.font(.footnote.weight(.semibold))
                }
            } else if let keys {
                if keys.keys.isEmpty {
                    Button { adding = true } label: {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("models.keys.emptyTitle").font(.body.weight(.semibold)).foregroundStyle(Palette.text)
                            Text("models.keys.emptyBody").font(.caption).foregroundStyle(Palette.secondary)
                        }
                        .padding(.vertical, 4)
                    }
                    .accessibilityIdentifier("addKeyEmpty")
                } else {
                    ForEach(keys.keys) { key in keyRow(key, inUse: keys.inUse == key.id ? keys.selectedModel : nil) }
                }
            } else {
                ProgressView().frame(maxWidth: .infinity)
            }
            if let actionError {
                Text(actionError).font(.footnote).foregroundStyle(.red)
            }
        } header: {
            SourceHeader(title: "models.keys.title", tag: "models.keys.billing") {
                Button { adding = true } label: { Label("models.keys.add", systemImage: "plus") }
                    .disabled(store == nil)
                    .accessibilityIdentifier("addKey")
            }
        } footer: {
            Text(keptFooter)
        }
    }

    private func keyRow(_ key: OwnKey, inUse: String?) -> some View {
        HStack(spacing: 12) {
            VendorLogo(company: key.company, size: 32)
            VStack(alignment: .leading, spacing: 3) {
                Text(verbatim: key.displayName).font(.body.weight(.semibold)).lineLimit(1)
                Text(verbatim: "\(key.keyHint) · \(L("models.count %lld", key.models.count))")
                    .font(.caption).foregroundStyle(Palette.secondary).lineLimit(1)
            }
            .layoutPriority(1)
            Spacer(minLength: 8)
            if busy == key.id {
                ProgressView()
            } else if let inUse, key.models.count < 2 {
                InUseMark(text: inUse)
            } else if !key.models.isEmpty {
                ModelMenu(models: key.models, current: inUse) { use(key, $0) }
                    .accessibilityIdentifier("useKey")
            }
        }
        .padding(.vertical, 2)
        .swipeActions {
            Button("models.keys.remove", systemImage: "trash", role: .destructive) { removing = key }
        }
        .contextMenu {
            Button("models.keys.remove", systemImage: "trash", role: .destructive) { removing = key }
        }
    }

    private var keptFooter: LocalizedStringKey {
        switch store?.place {
        case .cloud: "models.keys.keptCloud"
        case .server: "models.keys.keptServer"
        default: "models.keys.keptPhone"
        }
    }

    // MARK: Local models (phone only)

    private var localSection: some View {
        Section {
            ForEach(phone.local) { server in
                let inUse = phone.selection?.source == .local && phone.selection?.id == server.id ? phone.selection?.model : nil
                HStack(spacing: 12) {
                    VendorLogo(company: "ollama", size: 32)
                    VStack(alignment: .leading, spacing: 3) {
                        Text(verbatim: server.name).font(.body.weight(.semibold))
                        Text(verbatim: "\(server.host) · \(L("models.count %lld", server.models.count))")
                            .font(.caption).foregroundStyle(Palette.secondary).lineLimit(1)
                    }
                    .layoutPriority(1)
                    Spacer(minLength: 8)
                    if let inUse, server.models.count < 2 {
                        InUseMark(text: inUse)
                    } else {
                        ModelMenu(models: server.models, current: inUse) { phone.useLocal(server.id, model: $0) }
                    }
                }
                .padding(.vertical, 2)
                .swipeActions {
                    Button("models.keys.remove", systemImage: "trash", role: .destructive) { removingLocal = server }
                }
            }
            Button { addingLocal = true } label: {
                Label("models.local.add", systemImage: "plus.circle")
            }
            .accessibilityIdentifier("addLocal")
        } header: {
            SourceHeader(title: "models.local.title", tag: "models.local.billing")
        } footer: {
            Text("models.local.footer")
        }
    }

    // MARK: Actions

    private func load() async {
        guard let store else {
            keys = .empty
            return
        }
        do {
            apply(try await store.list())
            loadError = nil
        } catch {
            loadError = error.localizedDescription
        }
    }

    private func apply(_ list: OwnKeyList) {
        keys = list
        if model.server != nil { model.serverKeys = list }
    }

    private func use(_ key: OwnKey, _ choice: String) {
        guard let store else { return }
        busy = key.id
        actionError = nil
        Task {
            defer { busy = nil }
            do {
                apply(try await store.use(key.id, model: choice))
                Haptics.success()
            } catch {
                actionError = error.localizedDescription
            }
        }
    }

    private func remove(_ key: OwnKey) {
        guard let store else { return }
        busy = key.id
        actionError = nil
        Task {
            defer { busy = nil }
            do {
                try await store.remove(key.id)
                await load()
            } catch {
                actionError = error.localizedDescription
            }
        }
    }
}

/// "我的 API Key  [厂商直接收费]" with an optional trailing action.
struct SourceHeader<Trailing: View>: View {
    var title: LocalizedStringKey
    var tag: LocalizedStringKey
    var trailing: Trailing

    init(title: LocalizedStringKey, tag: LocalizedStringKey, @ViewBuilder trailing: () -> Trailing = { EmptyView() }) {
        self.title = title
        self.tag = tag
        self.trailing = trailing()
    }

    var body: some View {
        HStack(spacing: 8) {
            Text(title).font(.subheadline.weight(.semibold)).foregroundStyle(Palette.text)
            Text(tag)
                .font(.caption2.weight(.medium))
                .foregroundStyle(Palette.secondary)
                .padding(.horizontal, 6)
                .padding(.vertical, 2)
                .background(Palette.raised, in: RoundedRectangle(cornerRadius: 4))
            Spacer(minLength: 4)
            trailing.font(.subheadline.weight(.medium)).textCase(nil)
        }
        .textCase(nil)
    }
}

/// "Use" opening a menu of a source's models; with `current`, the model in use opens the same menu to switch.
private struct ModelMenu: View {
    var models: [KeyModel]
    var current: String?
    var pick: (String) -> Void

    var body: some View {
        Menu {
            ForEach(models) { choice in
                Button {
                    if choice.id != current { pick(choice.id) }
                } label: {
                    if choice.id == current {
                        Label(choice.label, systemImage: "checkmark")
                    } else {
                        Text(verbatim: choice.label)
                    }
                }
            }
        } label: {
            if let current {
                InUseMark(text: current).fixedSize()
            } else {
                Text("models.keys.use")
                    .font(.subheadline.weight(.medium))
                    .padding(.horizontal, 10)
                    .padding(.vertical, 5)
                    .background(Palette.raised, in: Capsule())
                    .foregroundStyle(Palette.text)
            }
        }
    }
}

/// A green dot and the model in use.
struct InUseMark: View {
    var text: String

    var body: some View {
        HStack(spacing: 5) {
            Circle().fill(Color.green).frame(width: 7, height: 7)
            Text(verbatim: text).lineLimit(1).truncationMode(.middle)
        }
        .font(.caption.weight(.medium))
        .foregroundStyle(Palette.secondary)
        .frame(maxWidth: 150, alignment: .trailing)
        .accessibilityIdentifier("inUse")
    }
}

/// A vendor's logo on a white tile, or its initials when the app has no logo for it.
struct VendorLogo: View {
    var company: String
    var size: CGFloat = 28

    var body: some View {
        let shape = RoundedRectangle(cornerRadius: size * 0.24, style: .continuous)
        Group {
            if company == VendorCompany.custom {
                Image(systemName: "point.3.connected.trianglepath.dotted")
                    .font(.system(size: size * 0.46, weight: .semibold))
                    .foregroundStyle(Palette.text)
                    .frame(width: size, height: size)
                    .background(Palette.raised, in: shape)
            } else if UIImage(named: "vendor-\(company)") != nil {
                Image("vendor-\(company)")
                    .resizable()
                    .scaledToFit()
                    .padding(size * 0.12)
                    .frame(width: size, height: size)
                    .background(Color.white, in: shape)
                    .overlay(shape.stroke(Palette.hairline, lineWidth: 0.5))
            } else {
                Text(verbatim: company == "deepseek" ? "DS" : String(company.prefix(2)).uppercased())
                    .font(.system(size: size * 0.38, weight: .bold, design: .rounded))
                    .foregroundStyle(Palette.text)
                    .frame(width: size, height: size)
                    .background(Palette.raised, in: shape)
            }
        }
        .accessibilityHidden(true)
    }
}
