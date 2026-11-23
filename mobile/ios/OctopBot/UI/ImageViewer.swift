import SwiftUI

/// Images of one message, opened at `index`.
struct ImageGallery: Identifiable {
    let id = UUID()
    var images: [Data]
    var index: Int
}

/// Full-screen photos: swipe between them, pinch or double-tap to zoom, drag down to close.
struct ImageViewer: View {
    @Environment(\.dismiss) private var dismiss
    let gallery: ImageGallery
    @State private var page: Int
    @State private var drag: CGFloat = 0

    init(gallery: ImageGallery) {
        self.gallery = gallery
        _page = State(initialValue: gallery.index)
    }

    private var current: UIImage? {
        gallery.images.indices.contains(page) ? UIImage(data: gallery.images[page]) : nil
    }

    var body: some View {
        ZStack {
            Color.black.opacity(1 - min(abs(drag) / 400, 0.6)).ignoresSafeArea()
            TabView(selection: $page) {
                ForEach(Array(gallery.images.enumerated()), id: \.offset) { index, data in
                    ZoomableImage(data: data, onDragDown: { drag = $0 }, onDismiss: { dismiss() })
                        .tag(index)
                }
            }
            .tabViewStyle(.page(indexDisplayMode: gallery.images.count > 1 ? .automatic : .never))
            .offset(y: drag)
        }
        .overlay(alignment: .top) {
            HStack {
                Button { dismiss() } label: {
                    Image(systemName: "xmark").font(.headline).frame(width: 40, height: 40)
                        .background(.ultraThinMaterial, in: Circle())
                }
                .accessibilityLabel(Text("common.close"))
                Spacer()
                if let current {
                    let image = Image(uiImage: current)
                    ShareLink(item: image, preview: SharePreview(Text("chat.image"), image: image)) {
                        Image(systemName: "square.and.arrow.up").font(.headline).frame(width: 40, height: 40)
                            .background(.ultraThinMaterial, in: Circle())
                    }
                    .accessibilityLabel(Text("common.share"))
                }
            }
            .foregroundStyle(.white)
            .padding(.horizontal, 16)
            .opacity(drag == 0 ? 1 : 0)
        }
        .statusBarHidden()
        .presentationBackground(.clear)
    }
}

private struct ZoomableImage: View {
    let data: Data
    var onDragDown: (CGFloat) -> Void
    var onDismiss: () -> Void
    @State private var scale: CGFloat = 1
    @State private var lastScale: CGFloat = 1
    @State private var offset: CGSize = .zero
    @State private var lastOffset: CGSize = .zero

    var body: some View {
        if let image = UIImage(data: data) {
            Image(uiImage: image)
                .resizable()
                .scaledToFit()
                .scaleEffect(scale)
                .offset(offset)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .contentShape(Rectangle())
                .gesture(
                    MagnifyGesture()
                        .onChanged { value in scale = min(max(lastScale * value.magnification, 1), 5) }
                        .onEnded { _ in
                            lastScale = scale
                            if scale == 1 { reset() }
                        }
                )
                .simultaneousGesture(
                    DragGesture()
                        .onChanged { value in
                            if scale > 1 {
                                offset = CGSize(width: lastOffset.width + value.translation.width,
                                                height: lastOffset.height + value.translation.height)
                            } else if value.translation.height > 0, abs(value.translation.height) > abs(value.translation.width) {
                                onDragDown(value.translation.height)
                            }
                        }
                        .onEnded { value in
                            if scale > 1 {
                                lastOffset = offset
                            } else if value.translation.height > 120 {
                                onDismiss()
                            } else {
                                withAnimation(.snappy) { onDragDown(0) }
                            }
                        }
                )
                .onTapGesture(count: 2) {
                    withAnimation(.snappy) {
                        if scale > 1 { reset() } else {
                            scale = 2.5
                            lastScale = 2.5
                        }
                    }
                }
        }
    }

    private func reset() {
        scale = 1
        lastScale = 1
        offset = .zero
        lastOffset = .zero
    }
}
