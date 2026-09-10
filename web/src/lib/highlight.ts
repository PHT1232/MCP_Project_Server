/**
 * A minimal, dependency-free syntax highlighter for the node inspector (FR34,
 * AC13). Not a full grammar — a small stateful scanner that tags comments,
 * strings, numbers and a common keyword set. Kept tiny on purpose (NFR13): the
 * alternative (shiki / highlight.js) is far heavier than the whole rest of the
 * bundle. The renderer maps each token kind onto a DESIGN.md token colour, so
 * there are no colour literals here.
 */

export type TokenKind = "keyword" | "string" | "comment" | "number" | "text";

export interface Token {
  text: string;
  kind: TokenKind;
}

const KEYWORDS = new Set<string>([
  // shared across the languages pcs indexes
  "abstract", "and", "as", "async", "await", "break", "case", "catch", "class",
  "const", "continue", "def", "default", "del", "do", "elif", "else", "enum",
  "except", "export", "extends", "false", "final", "finally", "fn", "for", "from",
  "func", "function", "go", "if", "impl", "import", "in", "instanceof",
  "interface", "is", "lambda", "let", "match", "mod", "mut", "new", "nil", "none",
  "not", "null", "or", "package", "pass", "private", "protected", "pub", "public",
  "raise", "return", "self", "static", "struct", "super", "switch", "this",
  "throw", "trait", "true", "try", "type", "typeof", "use", "var", "void",
  "while", "with", "yield",
]);

const HASH_COMMENT_LANGS = new Set<string>([
  "python", "ruby", "shell", "bash", "toml", "yaml", "yml", "perl", "r", "makefile",
]);

const IDENT_CHAR = /[A-Za-z0-9_$]/;
const IDENT_START = /[A-Za-z_$]/;
const NUMBER = /^(0[xXbBoO][0-9a-fA-F_]+|\d[\d_]*\.?\d*(?:[eE][+-]?\d+)?)/;

function push(tokens: Token[], text: string, kind: TokenKind): void {
  if (text === "") {
    return;
  }
  const last = tokens[tokens.length - 1];
  if (last?.kind === kind) {
    last.text += text;
    return;
  }
  tokens.push({ text, kind });
}

/**
 * Tokenise `source`. Returns a flat token list; newlines stay inside token
 * `text` so the renderer can split into lines itself.
 */
export function highlight(source: string, language: string | null): Token[] {
  const lang = (language ?? "").toLowerCase();
  const hashComments = HASH_COMMENT_LANGS.has(lang);
  const tokens: Token[] = [];
  let i = 0;
  let plain = "";

  const flushPlain = (): void => {
    push(tokens, plain, "text");
    plain = "";
  };

  while (i < source.length) {
    const ch = source[i] ?? "";
    const next = source[i + 1] ?? "";

    // line comment
    if ((ch === "/" && next === "/") || (ch === "#" && hashComments)) {
      flushPlain();
      const end = source.indexOf("\n", i);
      const stop = end === -1 ? source.length : end;
      push(tokens, source.slice(i, stop), "comment");
      i = stop;
      continue;
    }

    // block comment
    if (ch === "/" && next === "*") {
      flushPlain();
      const end = source.indexOf("*/", i + 2);
      const stop = end === -1 ? source.length : end + 2;
      push(tokens, source.slice(i, stop), "comment");
      i = stop;
      continue;
    }

    // string (single / double / backtick, with triple-quote support)
    if (ch === '"' || ch === "'" || ch === "`") {
      flushPlain();
      const triple = source.slice(i, i + 3);
      const isTriple = triple === '"""' || triple === "'''";
      const delim = isTriple ? triple : ch;
      let j = i + delim.length;
      while (j < source.length) {
        if (source[j] === "\\") {
          j += 2;
          continue;
        }
        if (source.startsWith(delim, j)) {
          j += delim.length;
          break;
        }
        j += 1;
      }
      push(tokens, source.slice(i, Math.min(j, source.length)), "string");
      i = Math.min(j, source.length);
      continue;
    }

    // number
    if (/\d/.test(ch) && !(plain !== "" && IDENT_CHAR.test(plain[plain.length - 1] ?? ""))) {
      const m = NUMBER.exec(source.slice(i));
      if (m) {
        flushPlain();
        push(tokens, m[0], "number");
        i += m[0].length;
        continue;
      }
    }

    // identifier / keyword
    if (IDENT_START.test(ch)) {
      let j = i + 1;
      while (j < source.length && IDENT_CHAR.test(source[j] ?? "")) {
        j += 1;
      }
      const word = source.slice(i, j);
      if (KEYWORDS.has(word)) {
        flushPlain();
        push(tokens, word, "keyword");
      } else {
        plain += word;
      }
      i = j;
      continue;
    }

    plain += ch;
    i += 1;
  }
  flushPlain();
  return tokens;
}
