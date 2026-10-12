// Convert the Hevelius drawings to greyscale WebP for the sky chart: white engraving on
// black, which the chart turns into its own ink colour on a transparent ground.
//
// Usage: node make_figure_images.cjs <frontend dir> <hevelius dir> <output dir>
const { createRequire } = require("module")
const fs = require("fs")
const path = require("path")

const [frontend, source, target] = process.argv.slice(2)
// sharp ships with Next.js in the frontend; nothing is installed for this script.
const sharp = createRequire(frontend.replace(/[\\/]?$/, "/"))("sharp")

fs.mkdirSync(target, { recursive: true })
;(async () => {
	let bytes = 0
	const files = fs.readdirSync(source).filter(file => file.endsWith(".png"))
	for (const file of files) {
		const info = await sharp(path.join(source, file))
			.flatten({ background: "#000" })
			.grayscale()
			.webp({ quality: 78 })
			.toFile(path.join(target, file.replace(/\.png$/, ".webp")))
		bytes += info.size
	}
	console.log(files.length, "images,", Math.round(bytes / 1024), "kB")
})()
