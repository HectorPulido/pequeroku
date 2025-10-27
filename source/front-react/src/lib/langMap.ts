const langMap: Record<string, string> = {
	// Scripting & Markup
	txt: "plaintext",
	log: "log",
	md: "markdown",
	markdown: "markdown",
	mdx: "markdown",
	html: "html",
	htm: "html",
	xml: "xml",
	xsd: "xml",
	xsl: "xml",
	svg: "xml",
	json: "json",
	yml: "yaml",
	yaml: "yaml",
	toml: "toml",
	ini: "ini",
	cfg: "ini",
	conf: "ini",
	// Styles
	css: "css",
	scss: "scss",
	sass: "sass",
	less: "less",
	// Shell & CI
	sh: "shell",
	bash: "shell",
	zsh: "shell",
	fish: "shell",
	ps1: "powershell",
	psm1: "powershell",
	psd1: "powershell",
	dockerfile: "dockerfile",
	gitignore: "git-commit",
	// Web / Front-end
	js: "javascript",
	jsx: "javascript",
	ts: "typescript",
	tsx: "typescript",
	vue: "vue",
	// Back-end / General purpose
	py: "python",
	rb: "ruby",
	php: "php",
	pl: "perl",
	pm: "perl",
	r: "r",
	go: "go",
	rs: "rust",
	java: "java",
	kt: "kotlin",
	kts: "kotlin",
	swift: "swift",
	dart: "dart",
	lua: "lua",
	// .NET
	cs: "csharp",
	fs: "fsharp",
	vb: "vb",
	// C / C++ / Objective-C
	c: "c",
	cpp: "cpp",
	cc: "cpp",
	cxx: "cpp",
	h: "cpp",
	hpp: "cpp",
	mm: "objective-c",
	m: "objective-c",
	objc: "objective-c",
	// Functional & others
	hs: "haskell",
	erl: "erlang",
	ex: "elixir",
	exs: "elixir",
	clj: "clojure",
	cljs: "clojure",
	scala: "scala",
	groovy: "groovy",
	coffee: "coffeescript",
	// DevOps / Infra as Code
	tf: "terraform",
	tfvars: "terraform",
	ansible: "yaml",
	// Build / CI files
	makefile: "makefile",
	mk: "makefile",
	cmake: "cmake",
	cmakelists: "cmake",
	gradle: "groovy",
	pom: "xml",
	// Database / Query
	sql: "sql",
	cypher: "cypher",
	graphql: "graphql",
	// LaTeX / Academia
	tex: "latex",
	sty: "latex",
	cls: "latex",
	bib: "bibtex",
	// Extras
	bat: "bat",
	vbs: "vbscript",
};

export function detectLanguageFromPath(path: string | null | undefined): string {
	const fallback = "plaintext";
	if (!path) return fallback;
	const normalized = String(path).trim().toLowerCase();
	if (!normalized) return fallback;
	const fileName = normalized.split("/").pop() ?? normalized;
	if (!fileName) return fallback;
	if (langMap[fileName]) {
		return langMap[fileName];
	}
	const segments = fileName.split(".");
	if (segments.length < 2) {
		return fallback;
	}
	const baseName = segments.slice(0, -1).join(".") || fileName;
	if (langMap[baseName]) {
		return langMap[baseName];
	}
	const extension = segments.pop() ?? "";
	return langMap[extension] ?? fallback;
}
