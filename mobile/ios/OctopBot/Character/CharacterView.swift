import SwiftUI
import UIKit

enum BotMotion: Equatable { case idle, working, thinking, searching, waiting }

/// A Bot's animated character: DS Bot vector shapes in any ink, or the Chief octopus.
struct CharacterView: View {
    var look: Look
    var size: CGFloat = 32
    var motion: BotMotion = .idle
    /// Seeds the animation phase so a row of Bots doesn't move in lockstep.
    var seed: String = ""

    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        TimelineView(.animation(minimumInterval: 1 / 30, paused: reduceMotion)) { timeline in
            let pose = CharacterPose(time: timeline.date.timeIntervalSinceReferenceDate + phase, motion: motion, size: size)
            figure(pose: pose)
                .scaleEffect(x: pose.scaleX, y: pose.scaleY, anchor: UnitPoint(x: 0.5, y: 0.84))
                .rotationEffect(.degrees(pose.rotation), anchor: UnitPoint(x: 0.5, y: 0.84))
                .offset(x: pose.offsetX, y: pose.offsetY)
        }
        .frame(width: size, height: size)
        .accessibilityHidden(true)
    }

    private var phase: Double {
        let text = seed.isEmpty ? look.shape + look.color : seed
        let hash = text.unicodeScalars.reduce(UInt32(0)) { ($0 &* 31) &+ $1.value }
        return Double(hash % 5039) / 1000
    }

    @ViewBuilder
    private func figure(pose: CharacterPose) -> some View {
        if look.isOctopus {
            MascotImage.view.resizable().scaledToFit()
        } else {
            Canvas { context, canvasSize in
                draw(in: &context, size: canvasSize, pose: pose)
            }
        }
    }

    private func draw(in context: inout GraphicsContext, size canvasSize: CGSize, pose: CharacterPose) {
        guard let shape = Characters.shape(look.shape) else { return }
        let scale = min(canvasSize.width, canvasSize.height) / 100
        context.scaleBy(x: scale, y: scale)
        let style = FillStyle(eoFill: true)
        if look.color == "aurora" {
            context.fill(shape.body, with: .linearGradient(
                Gradient(stops: Characters.library.aurora),
                startPoint: CGPoint(x: 18, y: 10), endPoint: CGPoint(x: 78, y: 92)
            ), style: style)
        } else {
            context.fill(shape.body, with: .color(Characters.ink(look.color)), style: style)
        }
        for paint in shape.paints {
            context.fill(paint.path, with: .color(paint.color.opacity(paint.opacity)), style: style)
        }
        context.fill(shape.shade, with: .color(.black.opacity(0.07)), style: style)
        if let light = shape.light {
            context.fill(light, with: .color(.white.opacity(0.36)), style: style)
        }
        for eye in shape.eyes {
            var eyeContext = context
            eyeContext.translateBy(x: eye.x, y: eye.y)
            eyeContext.rotate(by: .degrees(eye.angle))
            eyeContext.scaleBy(x: 1, y: pose.blink)
            let white = Path(roundedRect: CGRect(x: -eye.w / 2, y: -eye.h / 2, width: eye.w, height: eye.h), cornerRadius: eye.w / 2)
            eyeContext.fill(white, with: .color(Color(red: 1, green: 0.988, blue: 0.961)))
            if size >= 24 {
                let center = CGPoint(x: eye.w * (0.07 + pose.look), y: eye.h * 0.05)
                let pupil = Path(ellipseIn: CGRect(
                    x: center.x - eye.w * 0.28, y: center.y - eye.h * 0.22, width: eye.w * 0.56, height: eye.h * 0.44
                ))
                eyeContext.fill(pupil, with: .color(Color(red: 0.176, green: 0.157, blue: 0.2)))
            }
        }
    }
}

/// Pure function of time and motion, mirroring the dashboard's CSS keyframes.
struct CharacterPose: Equatable {
    var scaleX: CGFloat = 1
    var scaleY: CGFloat = 1
    var rotation: Double = 0
    var offsetX: CGFloat = 0
    var offsetY: CGFloat = 0
    /// Eye openness, 1 = open.
    var blink: CGFloat = 1
    /// Pupil shift as a fraction of eye width.
    var look: CGFloat = 0

    init(time: Double, motion: BotMotion, size: CGFloat) {
        func wave(_ period: Double) -> Double { (1 - cos(2 * .pi * time / period)) / 2 }
        func swing(_ period: Double) -> Double { sin(2 * .pi * time / period) }
        switch motion {
        case .idle:
            let v = wave(4.2)
            offsetY = -0.02 * size * v
            scaleX = 1 + 0.012 * v
            scaleY = 1 + 0.027 * v
        case .working:
            let v = wave(1.05)
            offsetY = -0.04 * size * v
            scaleX = 1 - 0.01 * v
            scaleY = 1 + 0.025 * v
        case .thinking:
            let v = wave(2.8)
            rotation = -4 * v
            offsetY = -0.01 * size * v
        case .searching:
            let s = swing(2.2)
            offsetX = 0.03 * size * s
            look = 0.14 * s
        case .waiting:
            rotation = 5 * swing(3.8)
            offsetY = -0.01 * size * wave(1.9)
        }
        // Blink: a 120 ms close-and-open every 5.8 s.
        let cycle = time.truncatingRemainder(dividingBy: 5.8)
        if cycle < 0.12 {
            let t = cycle / 0.12
            blink = 1 - 0.88 * (t < 0.5 ? t * 2 : (1 - t) * 2)
        }
    }
}

enum MascotImage {
    static let image: UIImage = {
        if let path = Bundle.main.path(forResource: "octop-mascot", ofType: "webp"), let image = UIImage(contentsOfFile: path) {
            return image
        }
        return UIImage()
    }()
    static var view: Image { Image(uiImage: image) }
}

/// Several members' characters in one square, like the dashboard's GroupCharacter.
struct GroupCharacterView: View {
    var members: [BotProfile]
    var size: CGFloat = 36

    var body: some View {
        let shown = Array(members.prefix(4))
        let side = shown.count <= 1 ? size : (shown.count == 2 ? size * 2 / 3 : size / 2)
        let rest = size - side
        let seats: [CGPoint] = switch shown.count {
        case 0, 1: [.zero]
        case 2: [.zero, CGPoint(x: rest, y: rest)]
        case 3: [CGPoint(x: rest / 2, y: 0), CGPoint(x: 0, y: rest), CGPoint(x: rest, y: rest)]
        default: [.zero, CGPoint(x: rest, y: 0), CGPoint(x: 0, y: rest), CGPoint(x: rest, y: rest)]
        }
        ZStack(alignment: .topLeading) {
            ForEach(Array(shown.enumerated()), id: \.offset) { index, bot in
                CharacterView(look: bot.look, size: side, seed: bot.id)
                    .offset(x: seats[min(index, seats.count - 1)].x, y: seats[min(index, seats.count - 1)].y)
            }
        }
        .frame(width: size, height: size, alignment: .topLeading)
    }
}
