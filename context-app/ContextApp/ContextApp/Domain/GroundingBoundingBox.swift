import Foundation

struct GroundingBoundingBox: Equatable {
    let x: CGFloat
    let y: CGFloat
    let width: CGFloat
    let height: CGFloat

    init?(values: [Double]) {
        guard values.count == 4 else { return nil }
        guard values.allSatisfy(\.isFinite) else { return nil }
        guard values[2] > 0, values[3] > 0 else { return nil }

        x = CGFloat(values[0])
        y = CGFloat(values[1])
        width = CGFloat(values[2])
        height = CGFloat(values[3])
    }

    func screenRect(captureSize: CGSize, screenFrame: CGRect) -> CGRect? {
        guard captureSize.width > 0, captureSize.height > 0 else { return nil }

        let scaleX = screenFrame.width / captureSize.width
        let scaleY = screenFrame.height / captureSize.height
        let rectWidth = width * scaleX
        let rectHeight = height * scaleY
        let originX = screenFrame.minX + (x * scaleX)
        let originY = screenFrame.maxY - ((y + height) * scaleY)

        return CGRect(x: originX, y: originY, width: rectWidth, height: rectHeight)
    }
}

struct GroundingResponse: Decodable {
    let boundingBox: GroundingBoundingBox

    private enum CodingKeys: String, CodingKey {
        case boundingBox = "bounding_box"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        let values = try container.decode([Double].self, forKey: .boundingBox)
        guard let boundingBox = GroundingBoundingBox(values: values) else {
            throw DecodingError.dataCorruptedError(
                forKey: .boundingBox,
                in: container,
                debugDescription: "Expected [x, y, width, height] with positive width and height."
            )
        }

        self.boundingBox = boundingBox
    }
}
