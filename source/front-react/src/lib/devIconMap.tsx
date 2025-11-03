import type React from "react";

const langMap: Record<string, string> = {
	// Scripting & Markup
	txt: "markdown",
	log: "logstash",
	md: "markdown",
	markdown: "markdown",
	mdx: "markdown",
	html: "html5",
	htm: "html5",
	xml: "xml",
	xsd: "xml",
	xsl: "xml",
	svg: "xml",
	json: "json",
	yml: "yaml",
	yaml: "yaml",
	toml: "json",
	ini: "yaml",
	cfg: "yaml",
	conf: "yaml",
	// Styles
	css: "css3",
	scss: "sass",
	sass: "sass",
	less: "less",
	// Shell & CI
	sh: "bash",
	bash: "bash",
	zsh: "bash",
	fish: "bash",
	ps1: "powershell",
	psm1: "powershell",
	psd1: "powershell",
	dockerfile: "docker",
	gitignore: "git",
	// Web / Front-end
	js: "javascript",
	jsx: "javascript",
	ts: "typescript",
	tsx: "typescript",
	vue: "vuejs",
	svelte: "svelte",
	astro: "astro",
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
	vb: "visualbasic",
	// C / C++ / Objective-C
	c: "c",
	cpp: "cplusplus",
	cc: "cplusplus",
	cxx: "cplusplus",
	h: "c",
	hpp: "cplusplus",
	mm: "objectivec",
	m: "objectivec",
	objc: "objectivec",
	// Functional & others
	hs: "haskell",
	erl: "erlang",
	ex: "elixir",
	exs: "elixir",
	clj: "clojure",
	cljs: "clojurescript",
	scala: "scala",
	groovy: "groovy",
	coffee: "coffeescript",
	// DevOps / Infra as Code
	tf: "terraform",
	tfvars: "terraform",
	ansible: "ansible",
	// Build / CI files
	makefile: "cmake",
	mk: "cmake",
	cmake: "cmake",
	cmakelists: "cmake",
	gradle: "gradle",
	pom: "maven",
	// Database / Query
	sql: "sqlite",
	cypher: "neo4j",
	graphql: "graphql",
	// LaTeX / Academia
	tex: "latex",
	sty: "latex",
	cls: "latex",
	bib: "latex",
	// Extras
	bat: "msdos",
	vbs: "visualbasic",
};

interface LanguageIconProps {
	path: string | null | undefined;
}

export const LanguageIconFromPathComponent: React.FC<LanguageIconProps> = ({ path }) => {
	const theme_type: "plain" | "plain-wordmark" | "plain colored" | "plain-wordmark colored" =
		"plain colored";
	const fallback = "markdown";
	if (!path) return <i className={`devicon-${fallback}-${theme_type}`}></i>;
	const normalized = String(path).trim().toLowerCase();
	if (!normalized) return <i className={`devicon-${fallback}-${theme_type}`}></i>;
	const fileName = normalized.split("/").pop() ?? normalized;
	if (!fileName) return <i className={`devicon-${fallback}-${theme_type}`}></i>;
	if (langMap[fileName]) {
		return <i className={`devicon-${langMap[fileName]}-${theme_type}`}></i>;
	}
	const segments = fileName.split(".");
	if (segments.length < 2) {
		return <i className={`devicon-${fallback}-${theme_type}`}></i>;
	}
	const baseName = segments.slice(0, -1).join(".") || fileName;
	if (langMap[baseName]) {
		return <i className={`devicon-${langMap[baseName]}-${theme_type}`}></i>;
	}
	const extension = segments.pop() ?? "";
	const icon = langMap[extension] ?? fallback;
	return <i className={`devicon-${icon}-${theme_type}`}></i>;
};
