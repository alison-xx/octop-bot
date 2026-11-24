import QuickLook
import SwiftUI

/// A server Bot's profile like Grok's: its upcoming scheduled tasks (with on/off switches)
/// and a library of the files it made in my chats.
struct BotActivityView: View {
    let server: ServerBackend
    let bot: BotProfile
    @State private var tab = Tab.activity
    @State private var jobs: [ServerBackend.UpcomingJob]?
    @State private var files: [ServerBackend.LibraryFile]?
    @State private var showAll = false
    @State private var changing: String?
    @State private var opening: String?
    @State private var preview: URL?
    @State private var error: String?

    enum Tab: Hashable { case activity, library }

    var body: some View {
        List {
            Section {
                Picker("profile.tabs", selection: $tab) {
                    Text("profile.activity").tag(Tab.activity)
                    Text("profile.library").tag(Tab.library)
                }
                .pickerStyle(.segmented)
                .listRowBackground(Color.clear)
                .listRowInsets(EdgeInsets())
                .accessibilityIdentifier("profileTabs")
            }
            if let error {
                Section { Text(error).font(.footnote).foregroundStyle(.red) }
            }
            switch tab {
            case .activity: activity
            case .library: library
            }
        }
        .navigationTitle(bot.name)
        .navigationBarTitleDisplayMode(.inline)
        .quickLookPreview($preview)
        .task(id: tab) { await load() }
        .refreshable { await load(force: true) }
    }

    @ViewBuilder
    private var activity: some View {
        Section {
            if let jobs {
                if jobs.isEmpty {
                    Text("profile.noUpcoming").font(.subheadline).foregroundStyle(Palette.secondary)
                }
                ForEach(showAll ? jobs : Array(jobs.prefix(ServerBackend.UpcomingJob.firstShown))) { job in
                    HStack(spacing: 12) {
                        Image(systemName: "clock").foregroundStyle(Palette.secondary)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(job.name).lineLimit(1)
                            Text(job.schedule).font(.caption).foregroundStyle(Palette.secondary).lineLimit(1)
                        }
                        Spacer(minLength: 8)
                        Toggle("", isOn: Binding(get: { job.enabled }, set: { on in Task { await toggle(job, on) } }))
                            .labelsHidden()
                            .disabled(!job.canToggle || (changing != nil && changing != job.id))
                            .accessibilityLabel(Text("profile.toggle \(job.name)"))
                    }
                }
                if !showAll && jobs.count > ServerBackend.UpcomingJob.firstShown {
                    Button("profile.showMore") { withAnimation(.snappy) { showAll = true } }
                        .foregroundStyle(Palette.secondary)
                }
            } else {
                ProgressView().frame(maxWidth: .infinity)
            }
        } header: {
            Text("profile.upcoming")
        }
    }

    @ViewBuilder
    private var library: some View {
        if let files {
            if files.isEmpty {
                Section { Text("profile.noFiles").font(.subheadline).foregroundStyle(Palette.secondary) }
            }
            ForEach(ServerBackend.LibraryFile.grouped(files), id: \.0) { period, group in
                Section(period.title) {
                    ForEach(group) { file in
                        Button { Task { await open(file) } } label: {
                            HStack(spacing: 12) {
                                Image(systemName: file.symbol).foregroundStyle(Palette.secondary).frame(width: 22)
                                Text(file.name).foregroundStyle(Palette.text).lineLimit(1).truncationMode(.middle)
                                Spacer(minLength: 8)
                                if opening == file.id { ProgressView() }
                            }
                        }
                        .disabled(opening != nil)
                    }
                }
            }
        } else {
            Section { ProgressView().frame(maxWidth: .infinity) }
        }
    }

    private func load(force: Bool = false) async {
        do {
            switch tab {
            case .activity: if force || jobs == nil { jobs = try await server.upcoming(bot.id) }
            case .library: if force || files == nil { files = try await server.library(bot.id) }
            }
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func toggle(_ job: ServerBackend.UpcomingJob, _ on: Bool) async {
        changing = job.id
        jobs = jobs?.map { $0.id == job.id ? $0.with(enabled: on) : $0 }
        defer { changing = nil }
        do {
            try await server.setCronEnabled(bot.id, jobId: job.id, enabled: on)
            Haptics.tap()
        } catch {
            self.error = error.localizedDescription
        }
        await load(force: true)
    }

    /// Quick Look shows the file and its share button saves it to Files or sends it on.
    private func open(_ file: ServerBackend.LibraryFile) async {
        opening = file.id
        defer { opening = nil }
        do {
            preview = try await server.fetchLibraryFile(file)
        } catch {
            Haptics.error()
            self.error = error.localizedDescription
        }
    }
}

extension ServerBackend {
    struct UpcomingJob: Identifiable, Equatable {
        static let firstShown = 5
        var id: String
        var name: String
        var enabled: Bool
        var schedule: String
        var canToggle: Bool

        func with(enabled: Bool) -> UpcomingJob {
            var copy = self
            copy.enabled = enabled
            return copy
        }

        nonisolated static func parse(_ data: Any) -> [UpcomingJob] {
            ((data as? [String: Any])?["jobs"] as? [[String: Any]] ?? []).compactMap { row in
                guard let id = row["id"] as? String else { return nil }
                return UpcomingJob(
                    id: id, name: row["name"] as? String ?? id, enabled: row["enabled"] as? Bool ?? false,
                    schedule: row["schedule"] as? String ?? "", canToggle: row["can_toggle"] as? Bool ?? false)
            }
        }
    }

    struct LibraryFile: Identifiable, Equatable {
        enum Period: String, CaseIterable { case today, week, older }
        var name: String
        var path: String
        var mime: String?
        var period: Period
        /// `/api/agents/{id}/workspace/download?path=…`
        var url: String
        var id: String { path }

        nonisolated static func parse(_ data: Any) -> [LibraryFile] {
            ((data as? [String: Any])?["files"] as? [[String: Any]] ?? []).compactMap { row in
                guard let path = row["path"] as? String, let url = row["url"] as? String else { return nil }
                return LibraryFile(
                    name: row["name"] as? String ?? path, path: path, mime: row["mime"] as? String,
                    period: (row["period"] as? String).flatMap(Period.init(rawValue:)) ?? .older, url: url)
            }
        }

        /// Today, this week, older — each kept in the server's newest-first order, empty ones left out.
        nonisolated static func grouped(_ files: [LibraryFile]) -> [(Period, [LibraryFile])] {
            Period.allCases.compactMap { period in
                let group = files.filter { $0.period == period }
                return group.isEmpty ? nil : (period, group)
            }
        }

        nonisolated var symbol: String {
            let ext = (name as NSString).pathExtension.lowercased()
            let type = mime ?? ""
            if type.hasPrefix("image/") { return "photo" }
            if type.hasPrefix("video/") { return "film" }
            if type.hasPrefix("audio/") { return "waveform" }
            switch ext {
            case "xls", "xlsx", "csv", "numbers": return "tablecells"
            case "ppt", "pptx", "key": return "rectangle.on.rectangle"
            case "zip", "gz", "tgz", "tar", "7z", "rar": return "doc.zipper"
            case "pdf", "doc", "docx", "md", "txt", "rtf", "pages": return "doc.text"
            default: return type.hasPrefix("text/") ? "doc.text" : "doc"
            }
        }
    }

    private func botPath(_ agentId: String) -> String {
        "/api/octop-bot/bots/" + (agentId.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? agentId)
    }

    func upcoming(_ agentId: String) async throws -> [UpcomingJob] {
        UpcomingJob.parse(try await json(.get, botPath(agentId) + "/upcoming"))
    }

    func library(_ agentId: String) async throws -> [LibraryFile] {
        LibraryFile.parse(try await json(.get, botPath(agentId) + "/library"))
    }

    func setCronEnabled(_ agentId: String, jobId: String, enabled: Bool) async throws {
        let agent = agentId.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? agentId
        let job = jobId.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? jobId
        _ = try await json(.patch, "/api/agents/\(agent)/cron/\(job)", json: ["enabled": enabled])
    }

    /// A local copy to preview: through a signed object-store link on Octop Bot cloud, otherwise
    /// downloaded with this session.
    func fetchLibraryFile(_ file: LibraryFile) async throws -> URL {
        guard let link = URL(string: file.url) else { throw APIError(kind: .server, status: 502, message: nil) }
        let data: Data
        if isCloud {
            let (body, response) = try await URLSession.shared.data(from: try await downloadLink(for: link))
            guard let status = (response as? HTTPURLResponse)?.statusCode, (200..<300).contains(status) else {
                throw APIError(kind: .server, status: 502, message: nil)
            }
            data = body
        } else {
            data = try await fileData(for: link)
        }
        let folder = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let local = folder.appending(path: file.name.isEmpty ? "download" : file.name)
        try data.write(to: local)
        return local
    }
}

extension ServerBackend.LibraryFile.Period {
    var title: LocalizedStringKey {
        switch self {
        case .today: "profile.today"
        case .week: "profile.week"
        case .older: "profile.older"
        }
    }
}
