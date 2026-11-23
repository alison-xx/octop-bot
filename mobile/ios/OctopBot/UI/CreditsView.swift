import StoreKit
import SwiftUI

/// Settings → Credits: the Lynxce balance and App Store credit packs.
struct CreditsView: View {
    @Environment(AppModel.self) private var model
    @State private var store = CreditStore.shared
    @State private var notice: String?
    @State private var noticeIsError = false

    var body: some View {
        Form {
            Section {
                VStack(spacing: 6) {
                    Text("credits.balance").font(.subheadline).foregroundStyle(Palette.secondary)
                    Text(verbatim: model.balance ?? "—")
                        .font(.system(size: 40, weight: .semibold, design: .rounded))
                        .monospacedDigit()
                        .contentTransition(.numericText())
                        .accessibilityIdentifier("creditsBalance")
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 10)
            } footer: {
                Text("credits.shared").frame(maxWidth: .infinity, alignment: .center)
            }

            Section {
                switch store.phase {
                case .idle, .loading:
                    HStack { Spacer(); ProgressView(); Spacer() }
                case .unavailable:
                    Text("credits.unavailable").foregroundStyle(Palette.secondary)
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
        .navigationTitle("credits.title")
        .navigationBarTitleDisplayMode(.inline)
        .task {
            await model.refreshBalance()
            await store.load()
        }
        .refreshable {
            await model.refreshBalance()
            await store.load()
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
}
