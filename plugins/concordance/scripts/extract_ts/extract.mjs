// concordance TypeScript extractor. One file at a time, syntax only (the compiler's parser,
// never the type checker), so a file's facts depend on its own content and path and can be
// shared across worktrees. Reads [{path, content}] on stdin; writes FileFacts-shaped dicts.
// Module resolution (relative imports, index files, tsconfig paths) happens in Python.
import ts from "typescript";
import { readFileSync } from "node:fs";
import path from "node:path";

const MIN_LITERAL = 3;

const items = JSON.parse(readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify(items.map(safeExtract)));

function safeExtract(item) {
  try {
    return extractFile(item);
  } catch (err) {
    return { path: item.path, lang: "typescript", parsed_ok: false,
             error: `extractor error: ${String(err && err.message ? err.message : err)}`,
             symbols: [], refs: [], literals: [], guards: [] };
  }
}

function modName(p) { return "ts:" + p.replace(/\.[cm]?tsx?$/, ""); }
function isTestPath(p) {
  return /(^|\/)(__tests__|tests?)\//.test(p) || /\.(test|spec)\.[cm]?tsx?$/.test(p);
}

function specTarget(fromPath, spec) {
  if (spec.startsWith(".")) {
    const joined = path.posix.normalize(path.posix.join(path.posix.dirname(fromPath), spec));
    return { rel: true, base: "ts:" + joined.replace(/\.([cm]?[jt]sx?)$/, "") };
  }
  return { rel: false, base: `ts-bare:${spec}|` };
}
function memberTarget(t, member) {
  if (t.rel) return member ? `${t.base}.${member}` : t.base;
  return member ? `${t.base}${member}` : t.base;
}
function joinTarget(base, rest) {
  if (!rest) return base;
  return base.endsWith("|") ? base + rest : `${base}.${rest}`;
}

function extractFile({ path: p, content }) {
  const mod = modName(p);
  const isTest = isTestPath(p);
  const kind = p.endsWith("x") ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  const sf = ts.createSourceFile(p, content, ts.ScriptTarget.Latest, true, kind);
  const lineOf = (pos) => sf.getLineAndCharacterOfPosition(pos).line + 1;
  const facts = { path: p, lang: "typescript", parsed_ok: true, error: null,
                  symbols: [], refs: [], literals: [], guards: [] };
  const diags = sf.parseDiagnostics ?? [];
  if (diags.length) {
    const d = diags[0];
    facts.parsed_ok = false;
    facts.error = `SyntaxError: line ${lineOf(d.start ?? 0)}: ` +
      ts.flattenDiagnosticMessageText(d.messageText, " ");
    return facts;
  }

  const imports = new Map();
  const topDefs = new Set();
  for (const st of sf.statements) {
    if (ts.isImportDeclaration(st) && ts.isStringLiteral(st.moduleSpecifier) && st.importClause) {
      const t = specTarget(p, st.moduleSpecifier.text);
      const clause = st.importClause;
      if (clause.name) imports.set(clause.name.text, memberTarget(t, "default"));
      const nb = clause.namedBindings;
      if (nb && ts.isNamespaceImport(nb)) imports.set(nb.name.text, memberTarget(t, null));
      if (nb && ts.isNamedImports(nb)) {
        for (const el of nb.elements) {
          imports.set(el.name.text, memberTarget(t, (el.propertyName ?? el.name).text));
        }
      }
    } else if ((ts.isFunctionDeclaration(st) || ts.isClassDeclaration(st) ||
                ts.isInterfaceDeclaration(st) || ts.isTypeAliasDeclaration(st) ||
                ts.isEnumDeclaration(st)) && st.name) {
      topDefs.add(st.name.text);
    } else if (ts.isVariableStatement(st)) {
      for (const d of st.declarationList.declarations) {
        if (ts.isIdentifier(d.name)) topDefs.add(d.name.text);
      }
    } else if (ts.isExportDeclaration(st) && st.moduleSpecifier &&
               ts.isStringLiteral(st.moduleSpecifier) && st.exportClause &&
               ts.isNamedExports(st.exportClause)) {
      const t = specTarget(p, st.moduleSpecifier.text);
      for (const el of st.exportClause.elements) {
        addAlias(`${mod}.${el.name.text}`, memberTarget(t, (el.propertyName ?? el.name).text));
      }
    }
  }

  const stack = [];
  const seen = new Set();
  const comments = [];
  const commentPos = new Set();
  const current = () => (stack.length ? stack[stack.length - 1].qual : mod);
  const inFunction = () => stack.some((s) => s.kind === "function" || s.kind === "method");
  const classQual = () => {
    for (let i = stack.length - 1; i >= 0; i--) if (stack[i].kind === "class") return stack[i].qual;
    return null;
  };

  function addAlias(qualname, target) {
    facts.symbols.push({ qualname, kind: "alias", line_start: 1, line_end: 1, is_test: isTest,
                         signature: null, alias_of: target });
  }
  function addSymbol(qual, k, node, sig) {
    facts.symbols.push({ qualname: qual, kind: k, line_start: lineOf(node.getStart(sf)),
                         line_end: lineOf(node.getEnd()), is_test: isTest,
                         signature: sig ?? null, alias_of: null });
  }
  function addRef(target, k, node, args, src) {
    if (!target) return;
    const s = src ?? current();
    const line = lineOf(node.getStart(sf));
    const key = `${s}|${target}|${k}|${line}`;
    if (seen.has(key)) return;
    seen.add(key);
    facts.refs.push({ src: s, target, kind: k, line, args: args ?? null });
  }
  function dotted(node) {
    if (ts.isIdentifier(node)) return node.text;
    if (node.kind === ts.SyntaxKind.ThisKeyword) return "this";
    if (ts.isPropertyAccessExpression(node)) {
      const b = dotted(node.expression);
      return b ? `${b}.${node.name.text}` : null;
    }
    return null;
  }
  function resolveDotted(d) {
    const i = d.indexOf(".");
    const head = i < 0 ? d : d.slice(0, i);
    const rest = i < 0 ? "" : d.slice(i + 1);
    if (head === "this") {
      const c = classQual();
      if (!c || !rest) return null;
      return rest.includes(".") ? `?.${rest.split(".").pop()}` : `${c}.${rest}`;
    }
    if (imports.has(head)) return joinTarget(imports.get(head), rest);
    if (topDefs.has(head)) return `${mod}.${d}`;
    return rest ? `?.${rest.split(".").pop()}` : null;
  }
  function signature(params) {
    return params.map((prm, i) => [
      ts.isIdentifier(prm.name) ? prm.name.text : `_arg${i}`,
      prm.dotDotDotToken ? "vararg" : "pos",
      Boolean(prm.questionToken || prm.initializer || prm.dotDotDotToken),
    ]);
  }
  function hasDefaultExport(node) {
    const mods = ts.canHaveModifiers(node) ? ts.getModifiers(node) ?? [] : [];
    return mods.some((m) => m.kind === ts.SyntaxKind.DefaultKeyword);
  }
  function decorators(node, qual) {
    const decs = ts.canHaveDecorators(node) ? ts.getDecorators(node) ?? [] : [];
    for (const dec of decs) {
      const callee = ts.isCallExpression(dec.expression) ? dec.expression.expression : dec.expression;
      const d = dotted(callee);
      addRef(d && resolveDotted(d), "decorator", dec, null, qual);
    }
  }
  function collectComments(pos) {
    for (const range of ts.getLeadingCommentRanges(content, pos) ?? []) {
      if (commentPos.has(range.pos)) continue;
      commentPos.add(range.pos);
      const raw = content.slice(range.pos, range.end);
      const text = raw.replace(/^\/\/+|^\/\*+|\*+\/$/g, "").trim();
      if (text) comments.push({ line: lineOf(range.pos), text });
    }
  }

  function defn(node, name, k, params, bodyNode) {
    const qual = `${current()}.${name}`;
    addSymbol(qual, k, node, signature(params));
    decorators(node, qual);
    if (k === "function" && hasDefaultExport(node) && stack.length === 0) {
      addAlias(`${mod}.default`, qual);
    }
    stack.push({ qual, kind: k });
    ts.forEachChild(bodyNode ?? node, visit);
    stack.pop();
  }
  function classDefn(node) {
    const qual = `${current()}.${node.name.text}`;
    addSymbol(qual, "class", node, null);
    decorators(node, qual);
    if (hasDefaultExport(node) && stack.length === 0) addAlias(`${mod}.default`, qual);
    for (const h of node.heritageClauses ?? []) {
      for (const t of h.types) {
        const d = dotted(t.expression);
        addRef(d && resolveDotted(d), "inherit", t, null, qual);
      }
    }
    stack.push({ qual, kind: "class" });
    for (const m of node.members) visit(m);
    stack.pop();
  }
  function call(node) {
    const callee = node.expression;
    const d = dotted(callee);
    let target = d ? resolveDotted(d) : null;
    if (!d) {
      if (ts.isPropertyAccessExpression(callee)) {
        target = `?.${callee.name.text}`;
        visit(callee.expression);
      } else {
        visit(callee);
      }
    }
    const args = node.arguments ?? [];
    addRef(target, "call", node, {
      positional: args.filter((a) => !ts.isSpreadElement(a)).length,
      keywords: [], star: args.some((a) => ts.isSpreadElement(a)), dstar: false,
    });
    for (const a of args) visit(a);
  }

  function visit(node) {
    collectComments(node.getFullStart());
    if (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) return;
    if (ts.isFunctionDeclaration(node)) {
      return defn(node, node.name ? node.name.text : "default", "function", node.parameters);
    }
    if (ts.isClassDeclaration(node) && node.name) return classDefn(node);
    if (ts.isMethodDeclaration(node) && ts.isIdentifier(node.name)) {
      return defn(node, node.name.text, "method", node.parameters);
    }
    if (ts.isConstructorDeclaration(node)) return defn(node, "constructor", "method", node.parameters);
    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer &&
        (ts.isArrowFunction(node.initializer) || ts.isFunctionExpression(node.initializer)) &&
        stack.length === 0) {
      return defn(node, node.name.text, "function", node.initializer.parameters, node.initializer);
    }
    if ((ts.isInterfaceDeclaration(node) || ts.isTypeAliasDeclaration(node) ||
         ts.isEnumDeclaration(node)) && stack.length === 0) {
      addSymbol(`${mod}.${node.name.text}`, "type", node, null);
      return;
    }
    if (ts.isExportAssignment(node) && ts.isIdentifier(node.expression)) {
      const target = resolveDotted(node.expression.text);
      if (target) addAlias(`${mod}.default`, target);
      return;
    }
    if (ts.isCallExpression(node) || ts.isNewExpression(node)) return call(node);
    if (ts.isPropertyAccessExpression(node)) {
      const d = dotted(node);
      if (d && imports.has(d.split(".")[0])) {
        addRef(resolveDotted(d), "name", node);
        return;
      }
    }
    if (ts.isIdentifier(node) && imports.has(node.text)) addRef(resolveDotted(node.text), "name", node);
    if (ts.isIfStatement(node) && inFunction()) {
      facts.guards.push({ symbol: current(), kind: "if", line: lineOf(node.getStart(sf)),
                          text: node.expression.getText(sf) });
    }
    if (ts.isThrowStatement(node) && inFunction() && node.expression) {
      facts.guards.push({ symbol: current(), kind: "raise", line: lineOf(node.getStart(sf)),
                          text: node.expression.getText(sf) });
    }
    if ((ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) &&
        node.text.length >= MIN_LITERAL) {
      facts.literals.push({ kind: "string", text: node.text, line: lineOf(node.getStart(sf)),
                            symbol: current() });
    }
    ts.forEachChild(node, visit);
  }

  const lastLine = Math.max(1, lineOf(sf.getEnd()));
  facts.symbols.push({ qualname: mod, kind: "module", line_start: 1, line_end: lastLine,
                       is_test: isTest, signature: null, alias_of: null });
  for (const [local, target] of imports) addAlias(`${mod}.${local}`, target);
  ts.forEachChild(sf, visit);

  const spans = facts.symbols
    .filter((s) => !["module", "alias", "type"].includes(s.kind))
    .sort((a, b) => (a.line_end - a.line_start) - (b.line_end - b.line_start));
  for (const c of comments) {
    const owner = spans.find((s) => s.line_start <= c.line && c.line <= s.line_end);
    facts.literals.push({ kind: "comment", text: c.text, line: c.line,
                          symbol: owner ? owner.qualname : mod });
  }
  return facts;
}
