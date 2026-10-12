// Shrink a scanned Uranometria plate to a greyscale WebP for the sky chart.
// The chart turns paper into transparency and ink into its own ink colour itself,
// so this only has to keep the engraving legible at a small file size.
//
// Usage: node make_plate_image.cjs <frontend dir> <plate.jpg> <plate.webp>
const { createRequire } = require("module")

const [frontend, source, target] = process.argv.slice(2)
// sharp ships with Next.js in the frontend; nothing is installed for this script.
const sharp = createRequire(frontend.replace(/[\\/]?$/, "/"))("sharp")

sharp(source)
	.resize({ width: 1100 })
	.grayscale()
	.normalise()
	.webp({ quality: 72 })
	.toFile(target)
	.then(info => console.log(info.width, info.height, info.size))
