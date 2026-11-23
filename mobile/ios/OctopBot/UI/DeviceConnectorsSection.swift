import SwiftUI
import UIKit

/// Settings → Device connectors: Health, Calendar and Reminders, each off until the user turns it on.
struct DeviceConnectorsSection: View {
    @Environment(\.scenePhase) private var scenePhase
    @State private var connectors = DeviceConnectors.shared
    @State private var asking: DeviceCapability?

    var body: some View {
        Section {
            ForEach(DeviceCapability.allCases) { capability in
                if connectors.isAvailable[capability] == true {
                    Toggle(isOn: binding(capability)) {
                        Label {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(verbatim: L("device.\(capability.rawValue)"))
                                Text(verbatim: L("device.\(capability.rawValue).detail"))
                                    .font(.caption).foregroundStyle(Palette.secondary)
                            }
                        } icon: {
                            SettingsIcon(symbol: symbol(capability), color: color(capability))
                        }
                    }
                    .tint(.green)
                    .disabled(asking != nil)
                }
            }
        } header: {
            Text("device.section")
        } footer: {
            VStack(alignment: .leading, spacing: 6) {
                Text("device.footer")
                if !connectors.denied.isEmpty {
                    Text("device.denied")
                    Button("settings.openSystem") {
                        if let url = URL(string: UIApplication.openSettingsURLString) { UIApplication.shared.open(url) }
                    }
                    .font(.footnote.weight(.semibold))
                    .tint(.blue)
                }
            }
        }
        .onAppear { connectors.refresh() }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active { connectors.refresh() }
        }
    }

    private func binding(_ capability: DeviceCapability) -> Binding<Bool> {
        Binding {
            connectors.isOn(capability)
        } set: { on in
            asking = capability
            Task {
                await connectors.set(capability, on: on)
                asking = nil
            }
        }
    }

    private func symbol(_ capability: DeviceCapability) -> String {
        switch capability {
        case .health: "heart.fill"
        case .calendar: "calendar"
        case .reminders: "checklist"
        }
    }

    private func color(_ capability: DeviceCapability) -> Color {
        switch capability {
        case .health: .pink
        case .calendar: .red
        case .reminders: .orange
        }
    }
}
