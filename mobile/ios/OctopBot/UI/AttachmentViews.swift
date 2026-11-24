import SwiftUI

/// Files under an assistant reply: pictures as themselves, other files as cards in a sideways row.
struct AttachmentStrip: View {
    var files: [FileAttachment]

    var body: some View {
        let images = files.filter(\.isImage)
        let others = files.filter { !$0.isImage }
        VStack(alignment: .leading, spacing: 10) {
            ForEach(images) { ImageAttachmentCard(file: $0) }
            if others.count == 1, let file = others.first {
                FileAttachmentCard(file: file)
            } else if !others.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(alignment: .top, spacing: 10) {
                        ForEach(others) { FileAttachmentCard(file: $0) }
                    }
                    .padding(.vertical, 4)
                    .padding(.horizontal, 1)
                }
                .scrollClipDisabled()
            }
        }
    }
}

/// Open / share / save, shared by every card.
private struct AttachmentMenu: ViewModifier {
    @Environment(AppModel.self) private var model
    var file: FileAttachment

    func body(content: Content) -> some View {
        content.contextMenu {
            if let server = model.server {
                Button("file.open", systemImage: "eye") { Task { await FileOpener.open(file, from: server) } }
                Button("common.share", systemImage: "square.and.arrow.up") { Task { await FileOpener.share(file, from: server) } }
                Button("file.saveToFiles", systemImage: "folder") { Task { await FileOpener.saveToFiles(file, from: server) } }
            }
        }
    }
}

private struct CardPressStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .opacity(configuration.isPressed ? 0.72 : 1)
            .scaleEffect(configuration.isPressed ? 0.985 : 1)
            .animation(.easeOut(duration: 0.12), value: configuration.isPressed)
    }
}

/// A picture the Bot sent, shown as itself: rounded, at most 320 pt wide, its own aspect ratio.
struct ImageAttachmentCard: View {
    @Environment(AppModel.self) private var model
    @Environment(\.displayScale) private var scale
    var file: FileAttachment
    @State private var image: UIImage?
    @State private var failed = false

    var body: some View {
        Button {
            guard let server = model.server else { return }
            Task { await FileOpener.open(file, from: server) }
        } label: {
            Group {
                if let image {
                    Image(uiImage: image)
                        .resizable()
                        .aspectRatio(image.size, contentMode: .fit)
                        .frame(maxWidth: min(320, image.size.width), maxHeight: 420, alignment: .leading)
                } else if failed {
                    FileAttachmentRow(file: file, size: nil)
                        .frame(width: 240)
                } else {
                    RoundedRectangle(cornerRadius: 16, style: .continuous)
                        .fill(Palette.surface)
                        .frame(width: 240, height: 180)
                        .overlay { ProgressView() }
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
            .overlay {
                RoundedRectangle(cornerRadius: 16, style: .continuous).strokeBorder(Palette.hairline, lineWidth: image == nil ? 0 : 0.5)
            }
        }
        .buttonStyle(CardPressStyle())
        .modifier(AttachmentMenu(file: file))
        .accessibilityLabel(Text(file.name))
        .task(id: file.url) {
            guard let server = model.server else { return }
            image = await AttachmentStore.shared.thumbnail(file, on: server, size: CGSize(width: 640, height: 640), scale: scale)
            failed = image == nil
        }
    }
}

/// A file card like a messenger's: an optional first-page preview, then the type glyph, name and size.
struct FileAttachmentCard: View {
    @Environment(AppModel.self) private var model
    @Environment(\.colorScheme) private var scheme
    @Environment(\.displayScale) private var scale
    var file: FileAttachment
    @State private var size: Int64?
    @State private var thumbnail: UIImage?

    static let width: CGFloat = 248

    var body: some View {
        Button {
            guard let server = model.server else { return }
            Task { await FileOpener.open(file, from: server) }
        } label: {
            VStack(spacing: 0) {
                if let thumbnail {
                    Image(uiImage: thumbnail)
                        .resizable()
                        .scaledToFill()
                        .frame(width: Self.width, height: 150, alignment: .top)
                        .clipped()
                        .background(Palette.surface)
                    Rectangle().fill(Palette.hairline).frame(height: 0.5)
                }
                FileAttachmentRow(file: file, size: size)
            }
            .frame(width: Self.width)
            .background(scheme == .dark ? Palette.surface : Palette.background)
            .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
            .overlay { RoundedRectangle(cornerRadius: 14, style: .continuous).strokeBorder(Palette.hairline, lineWidth: 1) }
            .shadow(color: .black.opacity(scheme == .dark ? 0 : 0.06), radius: 6, y: 2)
        }
        .buttonStyle(CardPressStyle())
        .modifier(AttachmentMenu(file: file))
        .accessibilityElement(children: .combine)
        .task(id: file.url) {
            guard let server = model.server else { return }
            size = await AttachmentStore.shared.size(of: file, on: server)
            thumbnail = await AttachmentStore.shared.thumbnail(file, on: server, size: CGSize(width: Self.width, height: 150), scale: scale)
        }
    }
}

/// Glyph · name · size.
struct FileAttachmentRow: View {
    var file: FileAttachment
    var size: Int64?

    var body: some View {
        HStack(spacing: 12) {
            FileGlyph(kind: file.kind, label: FileCardText.typeLabel(file.name))
            VStack(alignment: .leading, spacing: 3) {
                Text(FileCardText.middleEllipsis(file.name))
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(Palette.text)
                    .lineLimit(1)
                Text(size.map(FileCardText.formatFileSize) ?? FileCardText.typeLabel(file.name))
                    .font(.caption)
                    .foregroundStyle(Palette.secondary)
                    .monospacedDigit()
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .contentShape(Rectangle())
    }
}

/// A sheet of paper with a folded corner; its bottom band is the file type's color with the type on it.
struct FileGlyph: View {
    var kind: FileKind
    var label: String

    var body: some View {
        ZStack(alignment: .bottom) {
            DocumentShape().fill(Color.white)
            DocumentShape().fill(kind.band)
                .mask(alignment: .bottom) { Rectangle().frame(height: 16) }
            Text(label)
                .font(.system(size: label.count > 3 ? 7.5 : 9, weight: .heavy, design: .rounded))
                .foregroundStyle(.white)
                .lineLimit(1)
                .minimumScaleFactor(0.6)
                .padding(.horizontal, 2)
                .frame(height: 16)
            DocumentShape().stroke(Color.black.opacity(0.12), lineWidth: 0.75)
            FoldShape().fill(Color(white: 0.86))
        }
        .frame(width: 34, height: 42)
        .accessibilityHidden(true)
    }
}

nonisolated private struct DocumentShape: Shape {
    func path(in rect: CGRect) -> Path {
        let fold = rect.width * 0.3, r: CGFloat = 4
        var path = Path()
        path.move(to: CGPoint(x: rect.minX + r, y: rect.minY))
        path.addLine(to: CGPoint(x: rect.maxX - fold, y: rect.minY))
        path.addLine(to: CGPoint(x: rect.maxX, y: rect.minY + fold))
        path.addLine(to: CGPoint(x: rect.maxX, y: rect.maxY - r))
        path.addQuadCurve(to: CGPoint(x: rect.maxX - r, y: rect.maxY), control: CGPoint(x: rect.maxX, y: rect.maxY))
        path.addLine(to: CGPoint(x: rect.minX + r, y: rect.maxY))
        path.addQuadCurve(to: CGPoint(x: rect.minX, y: rect.maxY - r), control: CGPoint(x: rect.minX, y: rect.maxY))
        path.addLine(to: CGPoint(x: rect.minX, y: rect.minY + r))
        path.addQuadCurve(to: CGPoint(x: rect.minX + r, y: rect.minY), control: CGPoint(x: rect.minX, y: rect.minY))
        path.closeSubpath()
        return path
    }
}

nonisolated private struct FoldShape: Shape {
    func path(in rect: CGRect) -> Path {
        let fold = rect.width * 0.3
        var path = Path()
        path.move(to: CGPoint(x: rect.maxX - fold, y: rect.minY))
        path.addLine(to: CGPoint(x: rect.maxX - fold, y: rect.minY + fold - 2))
        path.addQuadCurve(
            to: CGPoint(x: rect.maxX - fold + 2, y: rect.minY + fold),
            control: CGPoint(x: rect.maxX - fold, y: rect.minY + fold)
        )
        path.addLine(to: CGPoint(x: rect.maxX, y: rect.minY + fold))
        path.closeSubpath()
        return path
    }
}
