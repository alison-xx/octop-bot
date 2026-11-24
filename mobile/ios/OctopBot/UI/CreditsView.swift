import SafariServices
import StoreKit
import SwiftUI

/// Settings → Credits: the Lynxce balance, App Store credit packs and the last 30 days' usage.
/// A self-hosted server has no wallet: the page says nothing is billed here and shows usage only.
struct CreditsView: View {
    @Environment(AppModel.self) private var model
    @State private var store = CreditStore.shared
    @State private var notice: String?
    @State private var noticeIsError = false
    @State private var usage: UsageState = .loading

    enum UsageState: Equatable {
        case loading, failed
        case loaded(byBot: ServerBackend.UsageSummary, byModel: ServerBackend.UsageSummary)
    }

    private var hasWallet: Bool { model.creditAccount != nil }

    var body: some View {
        ScrollViewReader { proxy in
            Form {
                if hasWallet {
                    balanceSection { withAnimation(.snappy) { proxy.scrollTo("packs", anchor: .top) } }
                    if CreditPurchases.inApp { packsSection.id("packs") }
                } else {
                    Section {
                        Label("credits.selfHosted", systemImage: "server.rack")
                            .font(.subheadline)
                            .foregroundStyle(Palette.secondary)
                    }
                }
                // Usage is kept by an Octop server; direct-Lynxce mode has none.
                if model.server != nil { usageSections }
            }
        }
        .navigationTitle(hasWallet ? CreditPurchases.title : "usage.title")
        .navigationBarTitleDisplayMode(.inline)
        .task { await reload() }
        .refreshable { await reload() }
    }

    private func reload() async {
        async let balance: Void = model.refreshBalance()
        async let usage: Void = loadUsage()
        if hasWallet && CreditPurchases.inApp { await store.load() }
        _ = await (balance, usage)
    }

    private func loadUsage() async {
        guard let server = model.server else { return }
        if case .loaded = usage {} else { usage = .loading }
        do {
            let (byBot, byModel) = try await server.usage()
            usage = .loaded(byBot: byBot, byModel: byModel)
        } catch {
            if case .loaded = usage {} else { usage = .failed }
        }
    }

    // MARK: Balance

    private func balanceSection(recharge: @escaping () -> Void) -> some View {
        Section {
            VStack(spacing: 10) {
                Text("credits.balance").font(.subheadline).foregroundStyle(Palette.secondary)
                bigBalance
                if model.isLowBalance {
                    Label(CreditPurchases.inApp ? "credits.low" : "credits.lowNoPurchase", systemImage: "exclamationmark.triangle.fill")
                        .font(.footnote)
                        .foregroundStyle(.orange)
                        .multilineTextAlignment(.center)
                }
                if CreditPurchases.inApp {
                    Button(action: recharge) {
                        Text("credits.recharge")
                            .font(.headline)
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 12)
                            .background(Palette.text, in: Capsule())
                            .foregroundStyle(Palette.background)
                    }
                    .buttonStyle(.plain)
                    .padding(.top, 4)
                    .accessibilityIdentifier("recharge")
                }
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 10)
        } footer: {
            Text("credits.shared").frame(maxWidth: .infinity, alignment: .center)
        }
    }

    @ViewBuilder
    private var bigBalance: some View {
        let font = Font.system(size: 40, weight: .semibold, design: .rounded)
        switch model.balance {
        case .value(let credits)?:
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text(verbatim: LynxceBackend.formatCredits(credits))
                    .font(font)
                    .monospacedDigit()
                    .contentTransition(.numericText())
                    .accessibilityIdentifier("creditsBalance")
                Text("credits.unit").font(.headline).foregroundStyle(Palette.secondary)
            }
            .foregroundStyle(model.isLowBalance ? Color.orange : Palette.text)
        case .failed?:
            VStack(spacing: 4) {
                Text(verbatim: "—").font(font).foregroundStyle(Palette.secondary)
                Button("common.retry") { Task { await model.refreshBalance() } }
                    .font(.footnote.weight(.semibold))
                    .buttonStyle(.borderless)
            }
        case .loading?, nil:
            Text(verbatim: "0,000").font(font).redacted(reason: .placeholder)
        }
    }

    // MARK: App Store packs

    private var packsSection: some View {
        Section {
            switch store.phase {
            case .idle, .loading:
                HStack { Spacer(); ProgressView(); Spacer() }
            case .unavailable:
                // Not a dead end: the same wallet can be topped up on the website or the desktop app.
                VStack(alignment: .leading, spacing: 4) {
                    Text("credits.unavailable").foregroundStyle(Palette.secondary)
                    Text("credits.elsewhere").font(.footnote).foregroundStyle(Palette.secondary)
                }
            case .failed(let message):
                VStack(alignment: .leading, spacing: 8) {
                    Text(message).foregroundStyle(.red).font(.footnote)
                    Button("common.retry") { Task { await store.load() } }
                }
            case .ready:
                ForEach(store.offers) { offer in row(offer) }
            }
        } header: {
            Text("credits.packs")
        } footer: {
            if let notice {
                Text(notice).foregroundStyle(noticeIsError ? .red : Palette.secondary)
            } else {
                Text("credits.footer")
            }
        }
    }

    private func row(_ offer: CreditStore.Offer) -> some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text(L("credits.amount %@", LynxceBackend.formatCredits(offer.pack.credits))).font(.headline)
                if !offer.pack.name.isEmpty {
                    Text(verbatim: offer.pack.name).font(.caption).foregroundStyle(Palette.secondary)
                }
            }
            Spacer()
            Button {
                Task { await buy(offer) }
            } label: {
                Group {
                    if store.buying == offer.id {
                        ProgressView()
                    } else {
                        Text(verbatim: offer.product.displayPrice).monospacedDigit()
                    }
                }
                .frame(minWidth: 64)
            }
            .buttonStyle(.borderedProminent)
            .tint(Palette.text)
            .disabled(store.buying != nil)
            .accessibilityIdentifier("buy-\(offer.pack.id)")
        }
        .padding(.vertical, 2)
    }

    private func buy(_ offer: CreditStore.Offer) async {
        notice = nil
        switch await store.buy(offer) {
        case .credited:
            Haptics.success()
            noticeIsError = false
            notice = L("credits.done")
        case .pending:
            noticeIsError = false
            notice = L("credits.pending")
        case .cancelled:
            break
        case .failed(let message):
            noticeIsError = true
            notice = message
        }
    }

    // MARK: Usage

    @ViewBuilder
    private var usageSections: some View {
        Section {
            switch usage {
            case .loading:
                HStack { Spacer(); ProgressView(); Spacer() }
            case .failed:
                VStack(alignment: .leading, spacing: 8) {
                    Text("usage.failed").foregroundStyle(Palette.secondary)
                    Button("common.retry") { Task { await loadUsage() } }
                }
            case .loaded(let byBot, _):
                if byBot.totalTokens == 0 && byBot.modelCalls == 0 {
                    Text("usage.empty").foregroundStyle(Palette.secondary)
                } else {
                    count(key: "usage.tokens", byBot.totalTokens)
                    count(key: "usage.calls", byBot.modelCalls)
                }
            }
        } header: {
            Text("usage.last30")
        }
        if case .loaded(let byBot, let byModel) = usage, byBot.totalTokens > 0 || byBot.modelCalls > 0 {
            if !byBot.buckets.isEmpty {
                Section("usage.byBot") {
                    ForEach(byBot.buckets) { bucket in count(verbatim: bucket.label, bucket.totalTokens) }
                }
            }
            if !byModel.buckets.isEmpty {
                Section("usage.byModel") {
                    ForEach(byModel.buckets) { bucket in count(verbatim: bucket.label, bucket.totalTokens) }
                }
            }
        }
    }

    private func count(key title: LocalizedStringKey, _ value: Int) -> some View {
        LabeledContent {
            Text(verbatim: LynxceBackend.formatCount(value)).monospacedDigit()
        } label: {
            Text(title)
        }
    }

    private func count(verbatim title: String, _ value: Int) -> some View {
        LabeledContent {
            Text(verbatim: LynxceBackend.formatCount(value)).monospacedDigit()
        } label: {
            Text(verbatim: title).lineLimit(1)
        }
    }
}

extension CreditPurchases {
    /// "积分与充值" while packs are sold here, otherwise "积分".
    static var title: LocalizedStringKey { inApp ? "credits.title" : "credits.titleNoPurchase" }
}

/// 积分与充值 in its own sheet, opened from the home screen and from chat.
struct CreditsSheet: View {
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            CreditsView()
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("common.done") { dismiss() } } }
        }
    }
}

/// "余额 12,800 积分" in its three states: a placeholder while loading, "—" (and retry) after a
/// failure, and the number, in the warning colour when it is low.
struct BalanceLabel: View {
    @Environment(AppModel.self) private var model
    /// Off where the label sits inside a row that opens 积分与充值 (which refreshes anyway).
    var allowsRetry = true

    var body: some View {
        switch model.balance {
        case .value(let credits)?:
            Text(L("credits.balance.line %@", LynxceBackend.formatCredits(credits)))
                .monospacedDigit()
                .foregroundStyle(model.isLowBalance ? Color.orange : Palette.text)
        case .failed?:
            HStack(spacing: 6) {
                Text(L("credits.balance.line %@", "—")).foregroundStyle(Palette.secondary)
                if allowsRetry {
                    Button("common.retry") { Task { await model.refreshBalance() } }
                        .buttonStyle(.borderless)
                        .fontWeight(.semibold)
                }
            }
        case .loading?:
            Text(L("credits.balance.line %@", "0,000")).redacted(reason: .placeholder)
        case nil:
            EmptyView()
        }
    }
}

/// Home: who is signed in, where, and the balance; tapping it opens 积分与充值.
struct HomeAccountRow: View {
    @Environment(AppModel.self) private var model
    var open: () -> Void

    var body: some View {
        Button(action: open) {
            HStack(spacing: 12) {
                CharacterView(look: .chief, size: 34)
                VStack(alignment: .leading, spacing: 1) {
                    Text(model.accountName).font(.subheadline.weight(.semibold)).foregroundStyle(Palette.text).lineLimit(1)
                    Label(model.modeLabel, systemImage: model.modeSymbol)
                        .font(.caption)
                        .foregroundStyle(Palette.secondary)
                        .lineLimit(1)
                }
                Spacer(minLength: 8)
                BalanceLabel(allowsRetry: false).font(.footnote.weight(.semibold)).lineLimit(1)
                Image(systemName: "chevron.right").font(.caption.weight(.semibold)).foregroundStyle(Palette.secondary)
            }
            .padding(10)
            .background(Palette.surface, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("homeBalance")
    }
}

/// Top of chat when the balance is under 100: "积分快用完了，余额 N 积分" + 充值, dismissible.
struct LowBalanceBanner: View {
    @Environment(AppModel.self) private var model
    @State private var showCredits = false

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.orange)
            Text(L("credits.low.banner %@", LynxceBackend.formatCredits(model.credits ?? 0)))
                .font(.footnote)
                .foregroundStyle(Palette.text)
                .frame(maxWidth: .infinity, alignment: .leading)
            if CreditPurchases.inApp {
                Button("credits.recharge") { showCredits = true }
                    .buttonStyle(PillButtonStyle(filled: true))
            }
            Button {
                withAnimation(.snappy) { model.dismissLowBalance() }
            } label: {
                Image(systemName: "xmark").font(.footnote.weight(.semibold)).foregroundStyle(Palette.secondary)
                    .frame(width: 28, height: 28)
            }
            .buttonStyle(.plain)
            .accessibilityLabel(Text("common.close"))
        }
        .padding(.leading, 12)
        .padding(.trailing, 6)
        .padding(.vertical, 8)
        .background(Palette.surface, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .padding(.horizontal, 12)
        .padding(.bottom, 4)
        .sheet(isPresented: $showCredits) { CreditsSheet() }
        .accessibilityIdentifier("lowBalanceBanner")
    }
}

/// A reply that Lynxce billing stopped. Out of credits: top up, then "Continue" re-runs the turn.
/// Daily cap: credits are left, so no top-up; it resets on its own (or the cap can be raised).
struct OutOfCreditsCard: View {
    enum Reason { case outOfCredits, dailyLimit }

    @Environment(AppModel.self) private var model
    var reason: Reason = .outOfCredits
    /// Only the latest reply can be continued.
    var canContinue: Bool
    var onContinue: () -> Void
    @State private var showCredits = false

    static let accountCentre = URL(string: "https://admin.lynxce.cn")!

    private var outOfCredits: Bool { reason == .outOfCredits }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label {
                Text(outOfCredits ? "credits.out.title" : "credits.limit.title").font(.headline).foregroundStyle(Palette.text)
            } icon: {
                Image(systemName: outOfCredits ? "bolt.circle.fill" : "clock.badge.exclamationmark").foregroundStyle(.orange)
            }
            Text(outOfCredits ? (CreditPurchases.inApp ? "credits.out.body" : "credits.out.bodyNoPurchase") : "credits.limit.body").font(.subheadline).foregroundStyle(Palette.secondary)
            // Daily cap: the account centre, where the cap is raised (not a purchase). Out of credits:
            // only the App Store packs behind 充值 — App Store builds never link to a web checkout (3.1.1).
            if !outOfCredits {
                VStack(alignment: .leading, spacing: 2) {
                    Text("credits.limit.raise").foregroundStyle(Palette.secondary)
                    Button { FileOpener.present(SFSafariViewController(url: Self.accountCentre)) } label: {
                        Text(verbatim: "admin.lynxce.cn").underline()
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(.tint)
                    .accessibilityIdentifier("creditCardAccountLink")
                }
                .font(.footnote)
            }
            if outOfCredits && model.balance != nil {
                BalanceLabel().font(.footnote)
            }
            HStack(spacing: 8) {
                if outOfCredits && model.creditAccount != nil && CreditPurchases.inApp {
                    Button("credits.recharge") { showCredits = true }
                        .buttonStyle(PillButtonStyle(filled: true))
                        .accessibilityIdentifier("creditCardRecharge")
                }
                if canContinue {
                    Button("credits.continue", action: onContinue)
                        .buttonStyle(PillButtonStyle())
                        .accessibilityIdentifier("creditCardContinue")
                }
            }
            .padding(.top, 2)
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Palette.surface, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).stroke(Color.orange.opacity(0.35), lineWidth: 0.5))
        .sheet(isPresented: $showCredits) { CreditsSheet() }
    }
}
