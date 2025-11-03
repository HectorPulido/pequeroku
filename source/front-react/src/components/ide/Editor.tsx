import Editor, { type BeforeMount } from "@monaco-editor/react";
import type { editor } from "monaco-editor";
import type React from "react";
import { useCallback, useEffect, useMemo, useRef } from "react";
import type { Theme } from "@/lib/theme";

interface EditorProps {
	content: string;
	onChange: (content: string) => void;
	theme: Theme;
	language: string;
	isMobile?: boolean;
}

const DARK_THEME_ID = "pequeroku-monokai";
const LIGHT_THEME_ID = "pequeroku-crema";
let themesRegistered = false;

type MonacoNamespace = typeof import("monaco-editor");

const defineThemes = (monaco: MonacoNamespace) => {
	if (themesRegistered) {
		return;
	}

	monaco.editor.defineTheme(DARK_THEME_ID, {
		base: "vs-dark",
		inherit: true,
		rules: [
			{ token: "comment", foreground: "75715e", fontStyle: "italic" },
			{ token: "keyword", foreground: "f92672" },
			{ token: "number", foreground: "ae81ff" },
			{ token: "string", foreground: "e6db74" },
		],
		colors: {
			"editor.background": "#2d2d2d",
			"editor.foreground": "#f8f8f2",
			"editorLineNumber.foreground": "#909090",
			"editorCursor.foreground": "#f8f8f2",
			"editor.selectionBackground": "#49483e",
			"editor.lineHighlightBackground": "#323232",
			"editorIndentGuide.background": "#3b3a32",
			"editor.lineHighlightBorder": "#3b3a32",
		},
	});

	monaco.editor.defineTheme(LIGHT_THEME_ID, {
		base: "vs",
		inherit: true,
		rules: [
			{ token: "comment", foreground: "a38b6d", fontStyle: "italic" },
			{ token: "keyword", foreground: "b45a3c", fontStyle: "bold" },
			{ token: "number", foreground: "8c5e58" },
			{ token: "string", foreground: "7c6f57" },
			{ token: "type", foreground: "5b5b8c", fontStyle: "bold" },
			{ token: "function", foreground: "3a5a40" },
		],
		colors: {
			"editor.background": "#fdf6e3",
			"editor.foreground": "#4b3832",
			"editorLineNumber.foreground": "#c8b68c",
			"editorCursor.foreground": "#6d4c41",
			"editor.selectionBackground": "#e6d7b9",
			"editor.lineHighlightBackground": "#f5e9d4",
			"editorIndentGuide.background": "#e0d3b8",
			"editorIndentGuide.activeBackground": "#d2b48c",
			"editor.lineHighlightBorder": "#e6d7b9",
		},
	});
	themesRegistered = true;
};

const MonacoEditor: React.FC<EditorProps> = ({
	content,
	onChange,
	theme,
	language,
	isMobile = false,
}) => {
	const editorRef = useRef<editor.IStandaloneCodeEditor | null>(null);

	const handleBeforeMount = useCallback<BeforeMount>((monaco) => {
		defineThemes(monaco as MonacoNamespace);
	}, []);

	const computedOptions = useMemo<editor.IStandaloneEditorConstructionOptions>(() => {
		return {
			minimap: { enabled: !isMobile },
			fontSize: isMobile ? 16 : 13,
			wordWrap: isMobile ? "on" : "off",
			lineNumbers: isMobile ? "off" : "on",
			glyphMargin: !isMobile,
			folding: !isMobile,
			lineNumbersMinChars: isMobile ? 0 : 4,
			lineDecorationsWidth: isMobile ? 16 : 20,
			scrollbar: isMobile
				? { vertical: "hidden", horizontal: "hidden" }
				: { vertical: "auto", horizontal: "auto" },
			scrollBeyondLastLine: false,
			automaticLayout: true,
			smoothScrolling: !isMobile,
		};
	}, [isMobile]);

	useEffect(() => {
		if (editorRef.current) {
			editorRef.current.updateOptions(computedOptions);
		}
	}, [computedOptions]);

	const handleMount = (instance: editor.IStandaloneCodeEditor) => {
		editorRef.current = instance;
		instance.updateOptions(computedOptions);
	};

	return (
		<div className="flex-1 h-full">
			<Editor
				height="100%"
				defaultLanguage="plaintext"
				language={language || "plaintext"}
				theme={theme === "dark" ? DARK_THEME_ID : LIGHT_THEME_ID}
				value={content}
				onChange={(value) => onChange(value || "")}
				onMount={handleMount}
				beforeMount={handleBeforeMount}
				options={computedOptions}
			/>
		</div>
	);
};

export default MonacoEditor;
