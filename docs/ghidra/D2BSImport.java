// Imports the D2BS address map for Diablo II 1.14d (Game.exe) into the current program.
// Phase 1 parses d2bs_types.h with Ghidra's C parser and adds every type under the
// data type category /D2BS. Phase 2 applies each row of d2bs_symbols.tsv:
// FUNC -> function, name, prototype and plate comment; DATA -> label and data type;
// LABEL -> label and EOL comment; PATCH/COND_PATCH -> label, pre-comment and a "D2BS"
// bookmark. Rows flagged stale-pre-1.14d? get a Warning bookmark. Re-running the script
// does not duplicate labels, comments or bookmarks.
// Usage (GUI): open Game.exe 1.14d (x86:LE:32:default, compiler spec windows), let
// auto-analysis finish, then run this script from the Script Manager (category D2BS).
// d2bs_symbols.tsv and d2bs_types.h are read from the directory of this script. The
// DEFAULT_* constants below are the GUI defaults; script arguments override them.
// Usage (headless): analyzeHeadless <projectDir> <projectName> -process Game.exe
//   -scriptPath <repo>/docs/ghidra -postScript D2BSImport.java [dry-run] [skip-types]
//   [skip-signatures] [names=auto|keep|force] [types=replace|keep] [stale=mark|apply|skip]
//   [asm-only=skip|apply] [symbols=<tsv>] [header=<h>] [max-errors=<n>] [force]
// Documentation: docs/ghidra/README.md in the D2BS repository.
//@author D2BS documentation (docs/ghidra)
//@category D2BS

import java.io.ByteArrayInputStream;
import java.io.File;
import java.lang.reflect.Constructor;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import generic.jar.ResourceFile;
import ghidra.app.cmd.function.ApplyFunctionSignatureCmd;
import ghidra.app.script.GhidraScript;
import ghidra.app.util.cparser.C.CParser;
import ghidra.app.util.cparser.C.ParseException;
import ghidra.app.util.cparser.C.Token;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressOverflowException;
import ghidra.program.model.data.Category;
import ghidra.program.model.data.CategoryPath;
import ghidra.program.model.data.CharDataType;
import ghidra.program.model.data.Composite;
import ghidra.program.model.data.DataOrganization;
import ghidra.program.model.data.DataType;
import ghidra.program.model.data.DataTypeConflictHandler;
import ghidra.program.model.data.DataTypeManager;
import ghidra.program.model.data.DoubleDataType;
import ghidra.program.model.data.FloatDataType;
import ghidra.program.model.data.FunctionDefinition;
import ghidra.program.model.data.IntegerDataType;
import ghidra.program.model.data.LongDataType;
import ghidra.program.model.data.ShortDataType;
import ghidra.program.model.data.TypeDef;
import ghidra.program.model.data.Undefined;
import ghidra.program.model.data.UnsignedCharDataType;
import ghidra.program.model.data.UnsignedIntegerDataType;
import ghidra.program.model.data.UnsignedLongDataType;
import ghidra.program.model.data.UnsignedShortDataType;
import ghidra.program.model.data.VoidDataType;
import ghidra.program.model.data.WideCharDataType;
import ghidra.program.model.listing.Bookmark;
import ghidra.program.model.listing.BookmarkManager;
import ghidra.program.model.listing.BookmarkType;
import ghidra.program.model.listing.CodeUnit;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.Listing;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.symbol.SourceType;
import ghidra.program.model.symbol.Symbol;
import ghidra.program.model.symbol.SymbolTable;
import ghidra.program.model.symbol.SymbolType;
import ghidra.util.exception.CancelledException;

public class D2BSImport extends GhidraScript {

    // ------------------------------------------------------------------------------------
    // GUI defaults. Script arguments (headless, or setScriptArgs) override these.
    // ------------------------------------------------------------------------------------

    /** true: report what would change, change nothing. */
    static final boolean DEFAULT_DRY_RUN = false;
    /** true: do not parse d2bs_types.h; prototypes resolve against existing /D2BS types. */
    static final boolean DEFAULT_SKIP_TYPES = false;
    /** true: never apply FUNC prototypes (names, comments, bookmarks still applied). */
    static final boolean DEFAULT_SKIP_SIGNATURES = false;
    /**
     * auto: rename only default/analysis names; keep: never rename an existing function or
     * name it through a label (functions this run creates are named); force: always rename.
     */
    static final String DEFAULT_NAMES = "auto";
    /** replace: /D2BS types from the header replace same-named ones; keep: existing win. */
    static final String DEFAULT_TYPES = "replace";
    /** mark: stale rows get label + comment + Warning only; apply: like any row; skip. */
    static final String DEFAULT_STALE = "mark";
    /** skip: do not apply the declared prototype of asm-only FUNC rows; apply: do. */
    static final String DEFAULT_ASM_ONLY = "skip";
    /** number of errors and warnings listed in the summary. */
    static final int DEFAULT_MAX_ERRORS = 25;

    // ------------------------------------------------------------------------------------
    // Constants
    // ------------------------------------------------------------------------------------

    static final String SYMBOLS_FILE = "d2bs_symbols.tsv";
    static final String HEADER_FILE = "d2bs_types.h";
    static final String D2BS_CATEGORY = "/D2BS";
    static final String BOOKMARK_CATEGORY = "D2BS";
    static final long EXPECTED_IMAGE_BASE = 0x400000L;
    static final List<String> TSV_HEADER = Collections.unmodifiableList(Arrays.asList(
        "kind", "module", "name", "rva", "type", "extra", "status", "comment", "source"));
    static final List<String> KINDS = Collections.unmodifiableList(
        Arrays.asList("FUNC", "DATA", "LABEL", "PATCH", "COND_PATCH"));
    static final List<String> PATCH_TYPES =
        Collections.unmodifiableList(Arrays.asList("CALL", "JMP", "BYTES"));
    static final List<String> CALLING_CONVENTIONS = Collections.unmodifiableList(
        Arrays.asList("__stdcall", "__fastcall", "__cdecl", "__thiscall"));
    /** Comment lines starting with this word (followed by ':' or ' ') belong to the script. */
    static final String OWNED_PREFIX = "D2BS";
    /** CParser places every type parsed after '#line 1 "D2BS"' in category /D2BS. */
    static final String HEADER_LINE_DIRECTIVE = "#line 1 \"D2BS\"\n";

    private static final Pattern RVA_HEX = Pattern.compile("0x[0-9A-Fa-f]{1,8}");
    private static final Pattern RVA_ORD = Pattern.compile("ORD:([0-9]{1,5})");
    private static final Pattern EXTRA_KEY = Pattern.compile("[a-z_]+");
    private static final Pattern TYPE_WORDS =
        Pattern.compile("[A-Za-z_][A-Za-z0-9_]*( [A-Za-z_][A-Za-z0-9_]*)*");

    // ------------------------------------------------------------------------------------
    // Options
    // ------------------------------------------------------------------------------------

    /** Script options; parse() is pure so it can be tested without Ghidra. */
    static final class Options {
        boolean dryRun = DEFAULT_DRY_RUN;
        boolean skipTypes = DEFAULT_SKIP_TYPES;
        boolean skipSignatures = DEFAULT_SKIP_SIGNATURES;
        boolean force = false;
        String names = DEFAULT_NAMES;
        String types = DEFAULT_TYPES;
        String stale = DEFAULT_STALE;
        String asmOnly = DEFAULT_ASM_ONLY;
        int maxErrors = DEFAULT_MAX_ERRORS;
        String symbolsPath;
        String headerPath;

        /**
         * Parses script arguments: flags (dry-run, skip-types, skip-signatures, force, each
         * optionally =true/false) and key=value pairs. Leading dashes are ignored.
         * @throws IllegalArgumentException on an unknown argument or a bad value
         */
        static Options parse(String[] args) {
            Options o = new Options();
            if (args == null) {
                return o;
            }
            for (String raw : args) {
                if (raw == null) {
                    continue;
                }
                String a = raw.trim();
                while (a.startsWith("-")) {
                    a = a.substring(1);
                }
                if (a.isEmpty()) {
                    continue;
                }
                String key = a;
                String value = null;
                int eq = a.indexOf('=');
                if (eq >= 0) {
                    key = a.substring(0, eq).trim();
                    value = a.substring(eq + 1).trim();
                }
                key = key.toLowerCase(Locale.ROOT).replace('_', '-');
                switch (key) {
                    case "dry-run":
                    case "dryrun":
                        o.dryRun = parseBool(raw, value);
                        break;
                    case "skip-types":
                        o.skipTypes = parseBool(raw, value);
                        break;
                    case "skip-signatures":
                        o.skipSignatures = parseBool(raw, value);
                        break;
                    case "force":
                        o.force = parseBool(raw, value);
                        break;
                    case "names":
                        o.names = parseChoice(raw, value, "auto", "keep", "force");
                        break;
                    case "types":
                        o.types = parseChoice(raw, value, "replace", "keep");
                        break;
                    case "stale":
                        o.stale = parseChoice(raw, value, "mark", "apply", "skip");
                        break;
                    case "asm-only":
                        o.asmOnly = parseChoice(raw, value, "skip", "apply");
                        break;
                    case "max-errors":
                        o.maxErrors = parseCount(raw, value);
                        break;
                    case "symbols":
                        o.symbolsPath = requireValue(raw, value);
                        break;
                    case "header":
                        o.headerPath = requireValue(raw, value);
                        break;
                    default:
                        throw new IllegalArgumentException("unknown script argument '" + raw +
                            "' (see the header of D2BSImport.java)");
                }
            }
            return o;
        }

        private static boolean parseBool(String raw, String value) {
            if (value == null || value.isEmpty()) {
                return true;
            }
            switch (value.toLowerCase(Locale.ROOT)) {
                case "true": case "yes": case "1": case "on":
                    return true;
                case "false": case "no": case "0": case "off":
                    return false;
                default:
                    throw new IllegalArgumentException("'" + raw + "': expected true or false");
            }
        }

        private static String parseChoice(String raw, String value, String... allowed) {
            String v = requireValue(raw, value).toLowerCase(Locale.ROOT);
            for (String a : allowed) {
                if (a.equals(v)) {
                    return a;
                }
            }
            throw new IllegalArgumentException(
                "'" + raw + "': expected one of " + String.join("|", allowed));
        }

        private static int parseCount(String raw, String value) {
            try {
                int n = Integer.parseInt(requireValue(raw, value));
                if (n >= 0) {
                    return n;
                }
            }
            catch (NumberFormatException e) {
                // reported below
            }
            throw new IllegalArgumentException("'" + raw + "': expected a number >= 0");
        }

        private static String requireValue(String raw, String value) {
            if (value == null || value.isEmpty()) {
                throw new IllegalArgumentException("'" + raw + "': a value is required");
            }
            return value;
        }

        String describe() {
            return "dry-run=" + dryRun + " skip-types=" + skipTypes + " skip-signatures=" +
                skipSignatures + " names=" + names + " types=" + types + " stale=" + stale +
                " asm-only=" + asmOnly + " max-errors=" + maxErrors + " force=" + force;
        }
    }

    // ------------------------------------------------------------------------------------
    // TSV rows (pure helpers)
    // ------------------------------------------------------------------------------------

    /** One row of d2bs_symbols.tsv. */
    static final class Row {
        int line;
        String kind;
        String module;
        String name;
        String rvaText;
        String type;
        String extra;
        String status;
        String comment;
        String source;
        /** RVA, or -1 for an ordinal row. */
        long rva = -1;
        /** Ordinal for an ORD:n row, else -1. */
        int ordinal = -1;
        Map<String, String> extraMap = new LinkedHashMap<>();
        Set<String> flags = new LinkedHashSet<>();

        boolean isAlias() {
            return extraMap.containsKey("alias_of");
        }

        String aliasOf() {
            return extraMap.get("alias_of");
        }

        boolean has(String flag) {
            return flags.contains(flag);
        }

        boolean isStale() {
            for (String f : flags) {
                if (f.contains("stale")) {
                    return true;
                }
            }
            return false;
        }

        boolean isPatch() {
            return "PATCH".equals(kind) || "COND_PATCH".equals(kind);
        }

        String flagText() {
            return flags.isEmpty() ? "-" : String.join(",", flags);
        }

        int patchLength() {
            return Integer.parseInt(extraMap.get("len"));
        }

        @Override
        public String toString() {
            return kind + " " + name + " (" + source + ")";
        }
    }

    /**
     * Parses the whole TSV (lines without terminators). The first non-empty line must be the
     * header. Blank lines and lines starting with '#' are ignored. Bad rows are reported in
     * {@code errors} and left out.
     */
    static List<Row> parseTsv(List<String> lines, List<String> errors) {
        List<Row> rows = new ArrayList<>();
        boolean headerSeen = false;
        for (int i = 0; i < lines.size(); i++) {
            String line = lines.get(i);
            if (i == 0 && line.startsWith("\uFEFF")) {
                line = line.substring(1);
            }
            if (line.endsWith("\r")) {
                line = line.substring(0, line.length() - 1);
            }
            if (line.trim().isEmpty() || line.startsWith("#")) {
                continue;
            }
            if (!headerSeen) {
                List<String> cells = Arrays.asList(line.split("\t", -1));
                if (!cells.equals(TSV_HEADER)) {
                    errors.add("line " + (i + 1) + ": header must be '" +
                        String.join("<TAB>", TSV_HEADER) + "', found '" + line + "'");
                    return rows;
                }
                headerSeen = true;
                continue;
            }
            try {
                rows.add(parseRow(line, i + 1));
            }
            catch (IllegalArgumentException e) {
                errors.add("line " + (i + 1) + ": " + e.getMessage());
            }
        }
        if (!headerSeen) {
            errors.add("no header row found");
        }
        return rows;
    }

    /** Parses one data row. @throws IllegalArgumentException if the row violates the schema */
    static Row parseRow(String line, int lineNo) {
        String[] f = line.split("\t", -1);
        if (f.length != TSV_HEADER.size()) {
            throw new IllegalArgumentException(
                "expected " + TSV_HEADER.size() + " tab-separated fields, found " + f.length);
        }
        Row r = new Row();
        r.line = lineNo;
        r.kind = f[0].trim();
        r.module = f[1].trim();
        r.name = f[2].trim();
        r.rvaText = f[3].trim();
        r.type = f[4].trim();
        r.extra = f[5].trim();
        r.status = f[6].trim();
        r.comment = f[7].trim();
        r.source = f[8].trim();
        if (!KINDS.contains(r.kind)) {
            throw new IllegalArgumentException("unknown kind '" + r.kind + "'");
        }
        if (!isValidLabelName(r.name)) {
            throw new IllegalArgumentException("invalid label name '" + r.name + "'");
        }
        Matcher ord = RVA_ORD.matcher(r.rvaText);
        if (RVA_HEX.matcher(r.rvaText).matches()) {
            r.rva = Long.parseLong(r.rvaText.substring(2), 16);
        }
        else if (ord.matches()) {
            r.ordinal = Integer.parseInt(ord.group(1));
        }
        else {
            throw new IllegalArgumentException("bad rva '" + r.rvaText + "' for " + r.name);
        }
        r.extraMap = parseExtra(r.extra);
        for (String s : r.status.split(",")) {
            if (!s.trim().isEmpty()) {
                r.flags.add(s.trim());
            }
        }
        if (r.isPatch()) {
            if (!PATCH_TYPES.contains(r.type)) {
                throw new IllegalArgumentException(
                    r.name + ": patch type must be CALL, JMP or BYTES, found '" + r.type + "'");
            }
            String len = r.extraMap.get("len");
            if (len == null || !len.matches("[1-9][0-9]{0,3}")) {
                throw new IllegalArgumentException(r.name + ": extra needs len=<n>");
            }
            String target = r.extraMap.get("target");
            if (target == null || target.isEmpty()) {
                throw new IllegalArgumentException(r.name + ": extra needs target=<...>");
            }
            if ("COND_PATCH".equals(r.kind) && !r.extraMap.containsKey("cond")) {
                throw new IllegalArgumentException(r.name + ": COND_PATCH needs cond=<flag>");
            }
        }
        else if ("FUNC".equals(r.kind) && r.type.isEmpty()) {
            throw new IllegalArgumentException(r.name + ": FUNC row without prototype");
        }
        if (r.isAlias() && !isValidLabelName(r.aliasOf())) {
            throw new IllegalArgumentException(r.name + ": bad alias_of '" + r.aliasOf() + "'");
        }
        return r;
    }

    /** Parses 'k=v;k=v'. @throws IllegalArgumentException on malformed or repeated keys */
    static Map<String, String> parseExtra(String extra) {
        Map<String, String> m = new LinkedHashMap<>();
        if (extra == null || extra.trim().isEmpty()) {
            return m;
        }
        for (String part : extra.split(";")) {
            String p = part.trim();
            if (p.isEmpty()) {
                continue;
            }
            int eq = p.indexOf('=');
            if (eq <= 0) {
                throw new IllegalArgumentException("bad extra field '" + p + "'");
            }
            String k = p.substring(0, eq).trim();
            String v = p.substring(eq + 1).trim();
            if (!EXTRA_KEY.matcher(k).matches()) {
                throw new IllegalArgumentException("bad extra key '" + k + "'");
            }
            if (m.put(k, v) != null) {
                throw new IllegalArgumentException("repeated extra key '" + k + "'");
            }
        }
        return m;
    }

    /** Non-empty, no whitespace or control characters, Ghidra's length limit. */
    static boolean isValidLabelName(String name) {
        if (name == null || name.isEmpty() || name.length() > 2000) {
            return false;
        }
        for (int i = 0; i < name.length(); i++) {
            char c = name.charAt(i);
            if (Character.isWhitespace(c) || Character.isISOControl(c)) {
                return false;
            }
        }
        return true;
    }

    /** Groups rows by RVA, keeping the order of first appearance; ordinal rows are left out. */
    static Map<Long, List<Row>> groupByRva(List<Row> rows) {
        Map<Long, List<Row>> m = new LinkedHashMap<>();
        for (Row r : rows) {
            if (r.rva >= 0) {
                m.computeIfAbsent(r.rva, k -> new ArrayList<>()).add(r);
            }
        }
        return m;
    }

    /** Consistency warnings for a parsed TSV (duplicate names, alias targets). */
    static List<String> checkRows(List<Row> rows) {
        List<String> out = new ArrayList<>();
        Map<String, Row> byName = new HashMap<>();
        for (Row r : rows) {
            Row prev = byName.put(r.name, r);
            if (prev != null) {
                out.add("name " + r.name + " used by " + prev.source + " and " + r.source);
            }
        }
        for (Row r : rows) {
            if (!r.isAlias()) {
                continue;
            }
            Row t = byName.get(r.aliasOf());
            if (t == null) {
                out.add(r.name + ": alias_of target " + r.aliasOf() + " is not a row");
            }
            else if (t.rva != r.rva) {
                out.add(r.name + ": alias_of target " + r.aliasOf() + " has another rva");
            }
        }
        return out;
    }

    // ------------------------------------------------------------------------------------
    // Prototypes and C type strings (pure helpers)
    // ------------------------------------------------------------------------------------

    /** A FUNC prototype split into return type, calling convention, name and parameters. */
    static final class Proto {
        String ret;
        /** calling convention keyword, or "" if none is written */
        String cc;
        String name;
        /** parameter declarations; empty for (void) */
        List<String> params = new ArrayList<>();
    }

    /**
     * Splits 'RET [CC] NAME(PARAMS)' (an optional trailing ';' is allowed). VOID is
     * rewritten to void (winnt.h macro, see d2bs_types.h).
     * @throws IllegalArgumentException if the text is not such a prototype for {@code name}
     */
    static Proto splitPrototype(String text, String name) {
        if (text == null) {
            throw new IllegalArgumentException("no prototype");
        }
        String t = text.trim().replaceAll("\\s+", " ");
        if (t.endsWith(";")) {
            t = t.substring(0, t.length() - 1).trim();
        }
        t = t.replaceAll("\\bVOID\\b", "void");
        Matcher m = Pattern.compile("(?<![A-Za-z0-9_])" + Pattern.quote(name) + "\\s*\\(")
                .matcher(t);
        int start = -1;
        int open = -1;
        while (m.find()) {
            if (depthAt(t, m.start()) == 0) {
                start = m.start();
                open = m.end() - 1;
                break;
            }
        }
        if (start < 0) {
            throw new IllegalArgumentException("prototype does not contain '" + name + "('");
        }
        int close = matchParen(t, open);
        if (close < 0) {
            throw new IllegalArgumentException("unbalanced parentheses in '" + t + "'");
        }
        if (!t.substring(close + 1).trim().isEmpty()) {
            throw new IllegalArgumentException("unexpected text after the parameter list");
        }
        Proto p = new Proto();
        p.name = name;
        String head = t.substring(0, start).trim();
        p.cc = "";
        int sp = head.lastIndexOf(' ');
        String last = sp < 0 ? head : head.substring(sp + 1);
        if (CALLING_CONVENTIONS.contains(last)) {
            p.cc = last;
            head = sp < 0 ? "" : head.substring(0, sp).trim();
        }
        else if (last.startsWith("__")) {
            throw new IllegalArgumentException("unsupported calling convention '" + last + "'");
        }
        if (head.isEmpty()) {
            throw new IllegalArgumentException("missing return type");
        }
        p.ret = head;
        String inner = t.substring(open + 1, close).trim();
        if (!inner.isEmpty() && !inner.equals("void")) {
            for (String param : splitTopLevel(inner, ',')) {
                if (param.isEmpty()) {
                    throw new IllegalArgumentException("empty parameter in '" + t + "'");
                }
                p.params.add(param);
            }
        }
        return p;
    }

    /**
     * Returns the prototype as C text for CParser: VOID replaced, '(void)' for no
     * parameters, terminated by ';'. A function-pointer parameter 'R (CC* P)(A)' becomes
     * '&lt;name&gt;_&lt;P&gt;_t P' when that typedef is in {@code typedefNames} (d2bs_types.h
     * provides them), else 'R CC (*P)(A)', the form in which CParser keeps the convention.
     */
    static String normalizePrototype(String text, String name, Set<String> typedefNames) {
        Proto p = splitPrototype(text, name);
        List<String> params = new ArrayList<>();
        for (int i = 0; i < p.params.size(); i++) {
            params.add(rewriteFunctionPointerParam(name, p.params.get(i), i, typedefNames));
        }
        return p.ret + " " + (p.cc.isEmpty() ? "" : p.cc + " ") + name + "(" +
            (params.isEmpty() ? "void" : String.join(", ", params)) + ");";
    }

    /** See {@link #normalizePrototype}; returns non-function-pointer parameters unchanged. */
    static String rewriteFunctionPointerParam(String funcName, String param, int index,
            Set<String> typedefNames) {
        int open = -1;
        for (int i = 0; i < param.length(); i++) {
            if (param.charAt(i) == '(') {
                open = i;
                break;
            }
        }
        if (open < 0) {
            return param;
        }
        int close = matchParen(param, open);
        if (close < 0) {
            throw new IllegalArgumentException("unbalanced parameter '" + param + "'");
        }
        String rest = param.substring(close + 1).trim();
        if (!rest.startsWith("(") || matchParen(rest, 0) != rest.length() - 1) {
            throw new IllegalArgumentException("unsupported parameter '" + param + "'");
        }
        String ret = param.substring(0, open).trim();
        String decl = param.substring(open + 1, close).trim();
        String args = rest.substring(1, rest.length() - 1).trim();
        Matcher m = Pattern.compile("(__[A-Za-z]+)?\\s*\\*\\s*([A-Za-z_][A-Za-z0-9_]*)?")
                .matcher(decl);
        if (ret.isEmpty() || !m.matches()) {
            throw new IllegalArgumentException("unsupported parameter '" + param + "'");
        }
        String cc = m.group(1);
        String pname = m.group(2) != null ? m.group(2) : "param_" + (index + 1);
        if (cc != null && !CALLING_CONVENTIONS.contains(cc)) {
            throw new IllegalArgumentException("unsupported calling convention '" + cc + "'");
        }
        String typedef = funcName + "_" + pname + "_t";
        if (typedefNames != null && typedefNames.contains(typedef)) {
            return typedef + " " + pname;
        }
        return ret + " " + (cc == null ? "" : cc + " ") + "(*" + pname + ")(" +
            (args.isEmpty() ? "void" : args) + ")";
    }

    /** Splits on {@code sep} at bracket depth 0; parts are trimmed. */
    static List<String> splitTopLevel(String s, char sep) {
        List<String> parts = new ArrayList<>();
        int depth = 0;
        StringBuilder cur = new StringBuilder();
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (c == '(' || c == '[' || c == '{') {
                depth++;
            }
            else if (c == ')' || c == ']' || c == '}') {
                depth--;
            }
            if (c == sep && depth == 0) {
                parts.add(cur.toString().trim());
                cur.setLength(0);
            }
            else {
                cur.append(c);
            }
        }
        parts.add(cur.toString().trim());
        return parts;
    }

    /** Index of the ')' matching the '(' at {@code open}, or -1. */
    static int matchParen(String s, int open) {
        int depth = 0;
        for (int i = open; i < s.length(); i++) {
            char c = s.charAt(i);
            if (c == '(') {
                depth++;
            }
            else if (c == ')') {
                depth--;
                if (depth == 0) {
                    return i;
                }
            }
        }
        return -1;
    }

    private static int depthAt(String s, int pos) {
        int depth = 0;
        for (int i = 0; i < pos; i++) {
            char c = s.charAt(i);
            if (c == '(') {
                depth++;
            }
            else if (c == ')') {
                depth--;
            }
        }
        return depth;
    }

    /** A DATA type string split into its base name and pointer depth. */
    static final class TypeRef {
        String base;
        int pointers;
    }

    /**
     * Splits a DATA type such as 'UnitAny*', 'const char *' or 'DWORD'. Qualifiers and
     * struct/union/enum keywords are dropped.
     * @throws IllegalArgumentException for arrays, function types or other unsupported forms
     */
    static TypeRef splitDataType(String text) {
        if (text == null || text.trim().isEmpty()) {
            throw new IllegalArgumentException("empty type");
        }
        String t = text.trim().replaceAll("\\s+", " ");
        TypeRef r = new TypeRef();
        while (t.endsWith("*")) {
            r.pointers++;
            t = t.substring(0, t.length() - 1).trim();
        }
        List<String> words = new ArrayList<>();
        for (String w : t.split(" ")) {
            if (w.equals("const") || w.equals("volatile") || w.equals("struct") ||
                w.equals("union") || w.equals("enum")) {
                continue;
            }
            words.add(w);
        }
        String base = String.join(" ", words);
        if (base.isEmpty() || !TYPE_WORDS.matcher(base).matches()) {
            throw new IllegalArgumentException("unsupported data type '" + text + "'");
        }
        r.base = base;
        return r;
    }

    // ------------------------------------------------------------------------------------
    // Comments (pure helpers)
    // ------------------------------------------------------------------------------------

    /** True for comment lines written by this script ("D2BS:" or "D2BS ..."). */
    static boolean isOwnedLine(String line) {
        return line.startsWith(OWNED_PREFIX + ":") || line.startsWith(OWNED_PREFIX + " ");
    }

    /**
     * Removes every line written by this script from {@code existing} and appends
     * {@code ours}. Other text is kept. Returns null for an empty result. Idempotent:
     * merge(merge(x, l), l) equals merge(x, l).
     */
    static String mergeOwnedLines(String existing, List<String> ours) {
        List<String> kept = new ArrayList<>();
        if (existing != null && !existing.isEmpty()) {
            for (String line : existing.split("\n", -1)) {
                if (!isOwnedLine(line)) {
                    kept.add(line);
                }
            }
        }
        while (!kept.isEmpty() && kept.get(kept.size() - 1).trim().isEmpty()) {
            kept.remove(kept.size() - 1);
        }
        List<String> all = new ArrayList<>(kept);
        for (String l : ours) {
            all.add(l.replace('\n', ' ').replace('\r', ' '));
        }
        return all.isEmpty() ? null : String.join("\n", all);
    }

    /** "D2BS patch: CALL len=5 -> GameInput_Intercept (cond Vars.bMulti)". */
    static String patchLine(Row r, String targetSuffix) {
        String s = OWNED_PREFIX + " patch: " + r.type + " len=" + r.extraMap.get("len") +
            " -> " + r.extraMap.get("target") + (targetSuffix == null ? "" : targetSuffix);
        if (r.extraMap.containsKey("cond")) {
            s += " (cond " + r.extraMap.get("cond") + ")";
        }
        return s;
    }

    /** "D2BS: NAME [MODULE] flags SOURCE // comment" (EOL comment of DATA/LABEL rows). */
    static String rowLine(Row r) {
        return OWNED_PREFIX + ": " + r.name + " [" + r.module + "] " + r.flagText() + " " +
            r.source + (r.comment.isEmpty() ? "" : " // " + r.comment);
    }

    /**
     * Marks an owned line as belonging to address {@code at} (used when the row's address is
     * inside a code unit, so the comment is stored on the code unit that contains it):
     * "D2BS: x" -> "D2BS @at: x", "D2BS patch: x" -> "D2BS @at patch: x". The result is still
     * an owned line. {@code at == null} returns the line unchanged.
     */
    static String tagOwnedLine(String line, String at) {
        if (at == null || !isOwnedLine(line)) {
            return line;
        }
        return OWNED_PREFIX + " @" + at + line.substring(OWNED_PREFIX.length());
    }

    // ------------------------------------------------------------------------------------
    // Header unit splitting (pure helper, used for diagnostics only)
    // ------------------------------------------------------------------------------------

    /** A top-level declaration or directive of a C header. */
    static final class Unit {
        int start;
        int end;
        int line;
        String text;
    }

    /**
     * Splits C text into top-level units: a '#' directive line, or everything up to a ';'
     * at brace/paren depth 0. Comments outside units are dropped; comments inside are kept.
     */
    static List<Unit> splitHeaderUnits(String text) {
        List<Unit> units = new ArrayList<>();
        int n = text.length();
        int i = 0;
        int line = 1;
        int depth = 0;
        int unitStart = -1;
        int unitLine = 0;
        boolean atLineStart = true;
        while (i < n) {
            char c = text.charAt(i);
            if (c == '/' && i + 1 < n && text.charAt(i + 1) == '/') {
                while (i < n && text.charAt(i) != '\n') {
                    i++;
                }
                continue;
            }
            if (c == '/' && i + 1 < n && text.charAt(i + 1) == '*') {
                int e = text.indexOf("*/", i + 2);
                e = e < 0 ? n : e + 2;
                for (int k = i; k < e; k++) {
                    if (text.charAt(k) == '\n') {
                        line++;
                    }
                }
                i = e;
                continue;
            }
            if (c == '\n') {
                line++;
                atLineStart = true;
                i++;
                continue;
            }
            if (c == ' ' || c == '\t' || c == '\r' || c == '\f') {
                i++;
                continue;
            }
            if (c == '#' && atLineStart && unitStart < 0) {
                int e = i;
                while (e < n && text.charAt(e) != '\n') {
                    e++;
                }
                Unit u = new Unit();
                u.start = i;
                u.end = e;
                u.line = line;
                u.text = text.substring(i, e);
                units.add(u);
                i = e;
                continue;
            }
            atLineStart = false;
            if (unitStart < 0) {
                unitStart = i;
                unitLine = line;
            }
            if (c == '"' || c == '\'') {
                int k = i + 1;
                while (k < n && text.charAt(k) != c && text.charAt(k) != '\n') {
                    k += text.charAt(k) == '\\' ? 2 : 1;
                }
                i = Math.min(k + 1, n);
                continue;
            }
            if (c == '{' || c == '(' || c == '[') {
                depth++;
            }
            else if (c == '}' || c == ')' || c == ']') {
                depth--;
            }
            else if (c == ';' && depth == 0) {
                Unit u = new Unit();
                u.start = unitStart;
                u.end = i + 1;
                u.line = unitLine;
                u.text = text.substring(unitStart, i + 1);
                units.add(u);
                unitStart = -1;
            }
            i++;
        }
        if (unitStart >= 0) {
            Unit u = new Unit();
            u.start = unitStart;
            u.end = n;
            u.line = unitLine;
            u.text = text.substring(unitStart);
            units.add(u);
        }
        return units;
    }

    // ------------------------------------------------------------------------------------
    // Data type helpers (need Ghidra classes, no Program)
    // ------------------------------------------------------------------------------------

    /** Result of parsing d2bs_types.h. */
    static final class HeaderResult {
        boolean ok;
        List<String> errors = new ArrayList<>();
        List<String> warnings = new ArrayList<>();
    }

    /**
     * Creates an in-memory data type manager. Uses TransientDataTypeManager (Ghidra 12.2+) or
     * StandAloneDataTypeManager (deprecated in 12.2), whichever exists. The built-in wchar_t
     * is added up front: CParser otherwise looks it up in BuiltInDataTypeManager, which is
     * only populated once Ghidra's class searcher has run.
     */
    static DataTypeManager createScratchDtm(String name, DataOrganization org) throws Exception {
        String[] classNames = { "ghidra.program.database.data.TransientDataTypeManager",
            "ghidra.program.model.data.StandAloneDataTypeManager" };
        Exception last = null;
        for (String cn : classNames) {
            DataTypeManager dtm;
            try {
                Class<?> c = Class.forName(cn);
                Constructor<?> ctor = c.getConstructor(String.class, DataOrganization.class);
                dtm = (DataTypeManager) ctor.newInstance(name, org);
            }
            catch (ClassNotFoundException | NoSuchMethodException e) {
                last = e;
                continue;
            }
            int tx = dtm.startTransaction("D2BS built-ins");
            try {
                dtm.resolve(WideCharDataType.dataType, null);
            }
            finally {
                dtm.endTransaction(tx, true);
            }
            return dtm;
        }
        throw new IllegalStateException("no in-memory DataTypeManager class found", last);
    }

    /**
     * Parses {@code headerText} with CParser into {@code dtm} (types stored, category
     * /D2BS). Never throws for parse problems: they are returned in the result.
     */
    static HeaderResult parseHeader(DataTypeManager dtm, String headerText) {
        HeaderResult res = new HeaderResult();
        String[] lines = headerText.split("\n", -1);
        CParser parser = new CParser(dtm, true, null);
        try {
            parser.parse(new ByteArrayInputStream(
                (HEADER_LINE_DIRECTIVE + headerText).getBytes(StandardCharsets.UTF_8)));
        }
        catch (ParseException e) {
            // stream line 1 is the injected '#line' directive: header line = token line - 1
            res.errors.add(describeParseError(e, lines, -1));
        }
        catch (RuntimeException e) {
            res.errors.add("CParser failed: " + e);
        }
        catch (Error e) {
            if (e instanceof VirtualMachineError) {
                throw e;
            }
            res.errors.add("CParser failed: " + e);
        }
        String msgs = parseMessages(parser);
        if (!msgs.trim().isEmpty()) {
            for (String m : msgs.split("\n")) {
                if (!m.trim().isEmpty()) {
                    res.warnings.add("CParser: " + m.trim());
                }
            }
        }
        res.ok = res.errors.isEmpty();
        return res;
    }

    /**
     * CParser.getParseMessages() (non-fatal messages; Ghidra 10.2+). Called reflectively so
     * that the script also compiles on 10.0/10.1; returns "" where it does not exist.
     */
    static String parseMessages(CParser parser) {
        try {
            Object o = parser.getClass().getMethod("getParseMessages").invoke(parser);
            return o == null ? "" : o.toString();
        }
        catch (ReflectiveOperationException | RuntimeException e) {
            return "";
        }
    }

    /**
     * Parses every top-level unit of the header separately into a throwaway manager so that
     * all failing declarations are reported, not only the first one.
     */
    static List<String> diagnoseHeader(DataTypeManager scratch, String headerText) {
        List<String> out = new ArrayList<>();
        String[] lines = headerText.split("\n", -1);
        CParser parser = new CParser(scratch, true, null);
        try {
            parser.parse(new ByteArrayInputStream(
                HEADER_LINE_DIRECTIVE.getBytes(StandardCharsets.UTF_8)));
        }
        catch (ParseException e) {
            out.add("CParser rejects the #line directive: " + firstLine(e.getMessage()));
            return out;
        }
        for (Unit u : splitHeaderUnits(headerText)) {
            try {
                parser.parse(new ByteArrayInputStream(u.text.getBytes(StandardCharsets.UTF_8)));
            }
            catch (ParseException e) {
                // token lines restart at 1 for every unit, which starts at header line u.line
                out.add(describeParseError(e, lines, u.line - 1));
            }
            catch (RuntimeException e) {
                out.add(HEADER_FILE + ":" + u.line + ": " + e);
            }
            catch (Error e) {
                if (e instanceof VirtualMachineError) {
                    throw e;
                }
                out.add(HEADER_FILE + ":" + u.line + ": " + e);
            }
        }
        return out;
    }

    private static final Pattern AROUND_LINE = Pattern.compile("around line: (\\d+)");
    private static final Pattern AT_LINE = Pattern.compile(" at line \\d+, column \\d+");

    /**
     * Formats a CParser error as 'd2bs_types.h:LINE: message | source line'. LINE is the
     * parser-stream line of the offending token (syntax errors), or the stream line named in
     * CParser's 'Check around ... line: N' text (semantic errors such as an undefined type,
     * which carry no token), plus {@code lineOffset}.
     */
    static String describeParseError(ParseException e, String[] lines, int lineOffset) {
        String raw = e.getMessage() == null ? "" : e.getMessage();
        Token t = e.currentToken;
        if (t != null && t.next != null) {
            t = t.next;
        }
        int line = -1;
        if (t != null && t.beginLine > 0) {
            line = t.beginLine + lineOffset;
        }
        else {
            Matcher m = AROUND_LINE.matcher(raw);
            if (m.find()) {
                line = Integer.parseInt(m.group(1)) + lineOffset;
            }
        }
        StringBuilder msg = new StringBuilder();
        for (String l : raw.split("\n")) {
            String s = AT_LINE.matcher(l.trim()).replaceAll("");
            if (s.equals("near token: null")) {
                continue;
            }
            if (s.startsWith("Error:") || s.startsWith("near token") ||
                s.startsWith("Possibly Undefined") || s.startsWith("Encountered")) {
                if (msg.length() > 0) {
                    msg.append("; ");
                }
                msg.append(s);
            }
        }
        if (msg.length() == 0) {
            msg.append(firstLine(raw));
        }
        String where = HEADER_FILE + (line > 0 ? ":" + line : "");
        String src = (line > 0 && line <= lines.length) ? " | " + lines[line - 1].trim() : "";
        return where + ": " + msg + src;
    }

    private static String firstLine(String s) {
        if (s == null) {
            return "";
        }
        int nl = s.indexOf('\n');
        return (nl < 0 ? s : s.substring(0, nl)).trim();
    }

    /** True for the named types that are imported (not pointers, arrays or built-ins). */
    static boolean isNamedType(DataType dt) {
        return dt instanceof Composite || dt instanceof TypeDef ||
            dt instanceof FunctionDefinition || dt instanceof ghidra.program.model.data.Enum;
    }

    /** Named types in {@code root} and its sub-categories, sorted by path. */
    static List<DataType> collectTypes(DataTypeManager dtm, CategoryPath root) {
        List<DataType> out = new ArrayList<>();
        Category c = dtm.getCategory(root);
        if (c != null) {
            collect(c, out);
        }
        out.sort(Comparator.comparing(DataType::getPathName));
        return out;
    }

    private static void collect(Category c, List<DataType> out) {
        for (DataType dt : c.getDataTypes()) {
            if (isNamedType(dt)) {
                out.add(dt);
            }
        }
        for (Category sub : c.getCategories()) {
            collect(sub, out);
        }
    }

    /** {new, equivalent, conflicting} counts of {@code types} relative to {@code target}. */
    static int[] compareTypes(DataTypeManager target, List<DataType> types) {
        int[] r = new int[3];
        for (DataType dt : types) {
            DataType ex = target.getDataType(dt.getCategoryPath(), dt.getName());
            if (ex == null) {
                r[0]++;
            }
            else if (ex.isEquivalent(dt)) {
                r[1]++;
            }
            else {
                r[2]++;
            }
        }
        return r;
    }

    /** Adds {@code types} to {@code target} (caller holds a transaction on target). */
    static void addTypes(DataTypeManager target, List<DataType> types,
            DataTypeConflictHandler handler) {
        for (DataType dt : types) {
            target.addDataType(dt, handler);
        }
    }

    /** Copies the named types under {@code root} of {@code from} into {@code to}. */
    static int copyTypes(DataTypeManager from, CategoryPath root, DataTypeManager to) {
        List<DataType> types = collectTypes(from, root);
        int tx = to.startTransaction("D2BS copy types");
        try {
            addTypes(to, types, DataTypeConflictHandler.REPLACE_HANDLER);
        }
        finally {
            to.endTransaction(tx, true);
        }
        return types.size();
    }

    /** Names of the typedefs under /D2BS of {@code dtm}. */
    static Set<String> typedefNames(DataTypeManager dtm) {
        Set<String> s = new HashSet<>();
        for (DataType dt : collectTypes(dtm, new CategoryPath(D2BS_CATEGORY))) {
            if (dt instanceof TypeDef) {
                s.add(dt.getName());
            }
        }
        return s;
    }

    /**
     * Parses a normalized prototype against {@code universe} without storing anything.
     * @throws ParseException if CParser rejects it or yields no function named {@code name}
     */
    static FunctionDefinition parsePrototype(DataTypeManager universe, String normalized,
            String name) throws ParseException {
        CParser parser = new CParser(universe, false, null);
        parser.parse(new ByteArrayInputStream(normalized.getBytes(StandardCharsets.UTF_8)));
        DataType dt = parser.getFunctions().get(name);
        if (!(dt instanceof FunctionDefinition)) {
            throw new ParseException("no function definition named " + name + " was produced");
        }
        return (FunctionDefinition) dt;
    }

    /** C keyword types used by DATA rows that are not typedefs in d2bs_types.h. */
    static DataType builtinType(String base) {
        switch (base) {
            case "void": return VoidDataType.dataType;
            case "char": return CharDataType.dataType;
            case "unsigned char": return UnsignedCharDataType.dataType;
            case "short": return ShortDataType.dataType;
            case "unsigned short": return UnsignedShortDataType.dataType;
            case "int": return IntegerDataType.dataType;
            case "unsigned": return UnsignedIntegerDataType.dataType;
            case "unsigned int": return UnsignedIntegerDataType.dataType;
            case "long": return LongDataType.dataType;
            case "unsigned long": return UnsignedLongDataType.dataType;
            case "float": return FloatDataType.dataType;
            case "double": return DoubleDataType.dataType;
            case "wchar_t": return WideCharDataType.dataType;
            default: return null;
        }
    }

    /**
     * Resolves a DATA type string: base from /D2BS of {@code dtm}, else a C keyword type;
     * then one pointer level per '*'. Returns null if the base type is unknown.
     */
    static DataType resolveDataType(DataTypeManager dtm, String text) {
        TypeRef r = splitDataType(text);
        DataType dt = dtm.getDataType(new CategoryPath(D2BS_CATEGORY), r.base);
        if (dt == null) {
            dt = builtinType(r.base);
        }
        if (dt == null) {
            return null;
        }
        for (int i = 0; i < r.pointers; i++) {
            dt = dtm.getPointer(dt);
        }
        return dt;
    }

    // ------------------------------------------------------------------------------------
    // Run state
    // ------------------------------------------------------------------------------------

    /** Per-row log; decides the row's outcome. */
    private static final class RowLog {
        final Row row;
        final String where;
        final List<String> errors = new ArrayList<>();
        final List<String> warnings = new ArrayList<>();
        final List<String> actions = new ArrayList<>();
        String skipReason;
        /** true if this run created (or, in dry-run, would create) the row's function */
        boolean createdFunction;

        RowLog(Row row, String where) {
            this.row = row;
            this.where = where;
        }
    }

    /** Comment lines and bookmark texts collected for one address. */
    private static final class AddrCtx {
        final List<String> plate = new ArrayList<>();
        final List<String> pre = new ArrayList<>();
        final List<String> eol = new ArrayList<>();
        final List<String> notes = new ArrayList<>();
        final List<String> warns = new ArrayList<>();

        boolean hasComments() {
            return !plate.isEmpty() || !pre.isEmpty() || !eol.isEmpty();
        }

        /** Appends the comment lines of {@code o}, tagged with {@code at} (may be null). */
        void addCommentsFrom(AddrCtx o, String at) {
            for (String l : o.plate) {
                plate.add(tagOwnedLine(l, at));
            }
            for (String l : o.pre) {
                pre.add(tagOwnedLine(l, at));
            }
            for (String l : o.eol) {
                eol.add(tagOwnedLine(l, at));
            }
        }
    }

    /** Annotations of one row address, written after all rows have been applied. */
    private static final class Pending {
        final Address addr;
        final AddrCtx ctx;

        Pending(Address addr, AddrCtx ctx) {
            this.addr = addr;
            this.ctx = ctx;
        }
    }

    private Options opts;
    private Listing listing;
    private Memory memory;
    private SymbolTable symbolTable;
    private BookmarkManager bookmarks;
    private DataTypeManager programDtm;
    private DataTypeManager universe;
    private Set<String> protoTypedefs = new HashSet<>();
    private Address imageBase;
    private Map<String, Row> rowsByName = new HashMap<>();
    private final List<String> errors = new ArrayList<>();
    private final List<String> warnings = new ArrayList<>();
    private final Map<String, int[]> kindStats = new LinkedHashMap<>();
    private final Map<String, Integer> counters = new LinkedHashMap<>();
    private final List<Pending> pending = new ArrayList<>();
    /** entries whose function this run named (in dry-run: would name), see ensureLabel */
    private final Set<Address> functionsNamed = new HashSet<>();

    private void count(String key) {
        counters.merge(key, 1, Integer::sum);
    }

    private int counter(String key) {
        Integer v = counters.get(key);
        return v == null ? 0 : v;
    }

    private void error(String msg) {
        errors.add(msg);
        printerr("D2BS: " + msg);
    }

    private void warn(String msg) {
        warnings.add(msg);
    }

    // ------------------------------------------------------------------------------------
    // run()
    // ------------------------------------------------------------------------------------

    @Override
    protected void run() throws Exception {
        try {
            opts = Options.parse(getScriptArgs());
        }
        catch (IllegalArgumentException e) {
            printerr("D2BSImport: " + e.getMessage() + "; nothing was changed.");
            return;
        }
        if (currentProgram == null) {
            printerr("D2BSImport: no program is open.");
            return;
        }
        for (String k : KINDS) {
            kindStats.put(k, new int[3]);
        }
        println("D2BSImport: " + opts.describe());

        if (!sanityChecks()) {
            printerr("D2BSImport: sanity checks failed; nothing was changed " +
                "(pass 'force' to continue anyway).");
            return;
        }

        File tsvFile = locate(opts.symbolsPath, SYMBOLS_FILE, "symbols", true);
        if (tsvFile == null) {
            printerr("D2BSImport: " + SYMBOLS_FILE + " not found; nothing was changed.");
            return;
        }
        List<String> tsvErrors = new ArrayList<>();
        List<String> tsvLines;
        try {
            tsvLines = Files.readAllLines(tsvFile.toPath(), StandardCharsets.UTF_8);
        }
        catch (java.io.IOException e) {
            printerr("D2BSImport: cannot read " + tsvFile + " as UTF-8: " + e +
                "; nothing was changed.");
            return;
        }
        List<Row> rows = parseTsv(tsvLines, tsvErrors);
        for (String e : tsvErrors) {
            error(SYMBOLS_FILE + " " + e);
        }
        if (rows.isEmpty()) {
            printerr("D2BSImport: no usable rows in " + tsvFile + "; nothing was changed.");
            return;
        }
        for (String w : checkRows(rows)) {
            warn(SYMBOLS_FILE + ": " + w);
        }
        for (Row r : rows) {
            rowsByName.putIfAbsent(r.name, r);
        }
        println("D2BSImport: " + rows.size() + " rows from " + tsvFile);

        listing = currentProgram.getListing();
        memory = currentProgram.getMemory();
        symbolTable = currentProgram.getSymbolTable();
        bookmarks = currentProgram.getBookmarkManager();
        programDtm = currentProgram.getDataTypeManager();
        imageBase = currentProgram.getImageBase();

        DataTypeManager headerDtm = null;
        try {
            try {
                headerDtm = importTypes();
            }
            catch (CancelledException e) {
                throw e;
            }
            catch (Exception e) {
                error("types: phase 1 failed: " + e + "; continuing without importing types");
            }
            try {
                prepareUniverse(headerDtm);
            }
            catch (Exception e) {
                error("prototypes: cannot create the parse context (" + e + "); prototypes " +
                    "are not applied in this run");
                opts.skipSignatures = true;
            }
            applyRows(rows);
        }
        catch (CancelledException e) {
            // GhidraScript commits the script's transaction on the way out: report what
            // was done before the cancel (one Undo reverts the whole run)
            printSummary(rows, true);
            throw e;
        }
        finally {
            if (universe != null && universe != headerDtm) {
                universe.close();
            }
            if (headerDtm != null) {
                headerDtm.close();
            }
        }
        printSummary(rows, false);
    }

    /** Language, image base and program name checks. Returns false to abort. */
    private boolean sanityChecks() {
        boolean ok = true;
        String lang = currentProgram.getLanguageID().getIdAsString();
        String[] p = lang.split(":");
        if (p.length < 3 || !p[0].equals("x86") || !p[1].equals("LE") || !p[2].equals("32")) {
            printerr("D2BSImport: language is " + lang + ", expected x86:LE:32:default " +
                "(Game.exe is 32-bit little-endian x86).");
            ok = opts.force;
        }
        else if (p.length > 3 && !p[3].equals("default")) {
            warn("language variant is '" + p[3] + "', expected 'default'");
        }
        String cs = currentProgram.getCompilerSpec().getCompilerSpecID().getIdAsString();
        if (!cs.equals("windows") && !cs.equals("clangwindows")) {
            warn("compiler spec is '" + cs + "', expected 'windows' (x86win.cspec defines " +
                "__stdcall/__cdecl/__fastcall/__thiscall); calling conventions may not apply");
        }
        long base = currentProgram.getImageBase().getOffset();
        if (base != EXPECTED_IMAGE_BASE) {
            warn(String.format("image base is 0x%X, expected 0x%X; addresses are computed " +
                "as image base + RVA, so the VA comments in the TSV do not match", base,
                EXPECTED_IMAGE_BASE));
        }
        String name = currentProgram.getName();
        if (name == null || !name.toLowerCase(Locale.ROOT).startsWith("game")) {
            warn("program name is '" + name + "'; the data describes Diablo II 1.14d " +
                "Game.exe (the game version itself cannot be checked by this script)");
        }
        return ok;
    }

    /** Explicit argument, else next to the script, else (GUI only) a file dialog. */
    private File locate(String argPath, String fileName, String what, boolean required)
            throws CancelledException {
        if (argPath != null) {
            File f = new File(argPath);
            if (f.isFile()) {
                return f;
            }
            error(what + "=" + argPath + ": file not found");
            return null;
        }
        File dir = scriptDirectory();
        if (dir != null) {
            File f = new File(dir, fileName);
            if (f.isFile()) {
                return f;
            }
        }
        if (!isRunningHeadless()) {
            return askFile("Select " + fileName, "Open");
        }
        if (required) {
            error(fileName + " is not next to the script and no " + what + "= argument was given");
        }
        return null;
    }

    private File scriptDirectory() {
        ResourceFile src = getSourceFile();
        if (src == null) {
            return null;
        }
        ResourceFile parent = src.getParentFile();
        if (parent == null) {
            return null;
        }
        File f = parent.getFile(false);
        return f != null ? f : new File(parent.getAbsolutePath());
    }

    // ------------------------------------------------------------------------------------
    // Phase 1: types
    // ------------------------------------------------------------------------------------

    /**
     * Parses the header into a scratch manager and, unless dry-run, adds the /D2BS types to
     * the program. All or nothing: on a parse error no type is added. Returns the scratch
     * manager (caller closes it) or null.
     */
    private DataTypeManager importTypes() throws Exception {
        if (opts.skipTypes) {
            println("D2BSImport: phase 1 skipped (skip-types)");
            return null;
        }
        File headerFile = locate(opts.headerPath, HEADER_FILE, "header", false);
        if (headerFile == null) {
            error(HEADER_FILE + " not found; no types imported, prototypes use existing " +
                D2BS_CATEGORY + " types");
            return null;
        }
        String text = new String(Files.readAllBytes(headerFile.toPath()), StandardCharsets.UTF_8)
                .replace("\r\n", "\n");
        DataOrganization org = programDtm.getDataOrganization();
        DataTypeManager scratch = createScratchDtm("D2BS header", org);
        try {
            return importTypes(text, headerFile, org, scratch);
        }
        catch (Exception | Error e) {
            scratch.close();
            throw e;
        }
    }

    /** importTypes() body; returns {@code scratch}, or null after closing it. */
    private DataTypeManager importTypes(String text, File headerFile, DataOrganization org,
            DataTypeManager scratch) throws Exception {
        monitor.setMessage("D2BS: parsing " + HEADER_FILE);
        HeaderResult hr = parseHeader(scratch, text);
        for (String w : hr.warnings) {
            warn(w);
        }
        if (!hr.ok) {
            for (String e : hr.errors) {
                error("types: " + e);
            }
            DataTypeManager diag = createScratchDtm("D2BS diagnostics", org);
            try {
                List<String> all = diagnoseHeader(diag, text);
                for (String e : all) {
                    error("types (per declaration): " + e);
                }
            }
            finally {
                diag.close();
            }
            error("types: no type was imported because " + HEADER_FILE + " did not parse; " +
                "prototypes use existing " + D2BS_CATEGORY + " types");
            scratch.close();
            return null;
        }
        List<DataType> types = collectTypes(scratch, new CategoryPath(D2BS_CATEGORY));
        if (types.isEmpty()) {
            error("types: " + HEADER_FILE + " parsed but produced no type under " + D2BS_CATEGORY);
            scratch.close();
            return null;
        }
        int[] cmp = compareTypes(programDtm, types);
        String verb = opts.dryRun ? "would add" : "added";
        if (!opts.dryRun) {
            DataTypeConflictHandler h = "keep".equals(opts.types)
                    ? DataTypeConflictHandler.KEEP_HANDLER
                    : DataTypeConflictHandler.REPLACE_HANDLER;
            addTypes(programDtm, types, h);
        }
        println(String.format("D2BSImport: phase 1: %d types parsed from %s; %s %d new, " +
            "%d already equivalent, %d conflicting (%s)", types.size(), headerFile, verb, cmp[0],
            cmp[1], cmp[2], "keep".equals(opts.types) ? "existing kept" : "replaced"));
        counters.put("types.parsed", types.size());
        counters.put("types.new", cmp[0]);
        counters.put("types.equivalent", cmp[1]);
        counters.put("types.conflicting", cmp[2]);
        return scratch;
    }

    /**
     * The manager prototypes are parsed against: a copy of the program's /D2BS types (so
     * that ApplyFunctionSignatureCmd resolves to the existing types without .conflict
     * copies), or in dry-run the freshly parsed header.
     */
    private void prepareUniverse(DataTypeManager headerDtm) throws Exception {
        if (opts.dryRun && headerDtm != null) {
            universe = headerDtm;
        }
        else {
            universe = createScratchDtm("D2BS prototypes", programDtm.getDataOrganization());
            int n = copyTypes(programDtm, new CategoryPath(D2BS_CATEGORY), universe);
            if (n == 0) {
                warn("no types under " + D2BS_CATEGORY + "; prototypes that use D2BS types " +
                    "will not parse (functions are still named)");
            }
        }
        protoTypedefs = typedefNames(universe);
    }

    // ------------------------------------------------------------------------------------
    // Phase 2: rows
    // ------------------------------------------------------------------------------------

    private void applyRows(List<Row> rows) throws CancelledException {
        for (Row r : rows) {
            if (r.rva < 0) {
                RowLog log = new RowLog(r, "ORD:" + r.ordinal);
                log.skipReason = "ordinal rows are resolved at run time (GetProcAddress); " +
                    "not supported";
                finish(log);
            }
        }
        Map<Long, List<Row>> groups = groupByRva(rows);
        monitor.initialize(groups.size());
        monitor.setMessage("D2BS: applying " + rows.size() + " rows");
        for (Map.Entry<Long, List<Row>> g : groups.entrySet()) {
            if (monitor.isCancelled()) {
                throw new CancelledException();
            }
            applyGroup(g.getKey(), g.getValue());
            monitor.incrementProgress(1);
        }
        // comments and bookmarks last: the script makes no further listing changes, so the
        // code unit that holds each comment is the one the next run will see
        monitor.setMessage("D2BS: writing comments and bookmarks");
        writeAnnotations();
    }

    private void applyGroup(long rva, List<Row> rows) {
        Address addr;
        try {
            addr = imageBase.addNoWrap(rva);
        }
        catch (AddressOverflowException e) {
            for (Row r : rows) {
                RowLog log = new RowLog(r, String.format("rva 0x%X", rva));
                log.skipReason = "image base + RVA overflows the address space";
                finish(log);
            }
            return;
        }
        MemoryBlock block = memory.getBlock(addr);
        AddrCtx ctx = new AddrCtx();
        for (Row r : rows) {
            RowLog log = new RowLog(r, addr.toString());
            if (block == null) {
                log.skipReason = "address " + addr + " is not in any memory block";
                finish(log);
                continue;
            }
            boolean stale = r.isStale();
            if (stale && "skip".equals(opts.stale)) {
                log.skipReason = "stale row (stale=skip)";
                finish(log);
                continue;
            }
            if (stale) {
                ctx.warns.add(r.name + ": " + r.flagText() + " (" + r.source + "): not " +
                    "verified for 1.14d, see docs/memory/offsets.md");
            }
            try {
                if (stale && "mark".equals(opts.stale) && !r.isPatch()) {
                    markOnly(r, addr, ctx, log);
                }
                else if ("FUNC".equals(r.kind)) {
                    applyFunc(r, addr, block, ctx, log);
                }
                else if ("DATA".equals(r.kind)) {
                    applyData(r, addr, block, ctx, log);
                }
                else if ("LABEL".equals(r.kind)) {
                    // a LABEL row at a FUN_* entry names that function, except with names=keep
                    ensureLabel(addr, r.name, false, canTakeOver(SourceType.DEFAULT)
                            ? AtDefaultFunction.RENAME : AtDefaultFunction.SKIP, log);
                    ctx.eol.add(rowLine(r));
                }
                else {
                    applyPatch(r, addr, ctx, log);
                }
            }
            catch (Exception e) {
                log.errors.add("unexpected " + e.getClass().getSimpleName() + ": " +
                    e.getMessage());
            }
            finish(log);
        }
        if (block != null) {
            pending.add(new Pending(addr, ctx));
        }
    }

    /**
     * stale=mark: label (never primary, never the name of an existing function) + EOL comment;
     * no function, type or signature.
     */
    private void markOnly(Row r, Address addr, AddrCtx ctx, RowLog log) {
        ensureLabel(addr, r.name, false, AtDefaultFunction.SKIP, log);
        ctx.eol.add(rowLine(r));
        if ("FUNC".equals(r.kind)) {
            ctx.eol.add(OWNED_PREFIX + " proto: " + r.type + " (not applied: stale=mark)");
        }
        else if ("DATA".equals(r.kind) && !r.type.isEmpty()) {
            ctx.eol.add(OWNED_PREFIX + " type: " + r.type + " (not applied: stale=mark)");
        }
        count("stale.marked");
    }

    private void applyFunc(Row r, Address addr, MemoryBlock block, AddrCtx ctx, RowLog log) {
        if (r.isAlias()) {
            // secondary label only: an alias never names the function
            ensureLabel(addr, r.name, false, AtDefaultFunction.SKIP, log);
            ctx.plate.add(OWNED_PREFIX + " alias: " + r.name + " [" + r.module + "] " +
                r.flagText() + " " + r.source + " = " + r.type);
            count("signatures.alias");
            return;
        }
        ctx.plate.add(OWNED_PREFIX + ": " + r.name + " [" + r.module + "] " + r.flagText());
        ctx.plate.add(OWNED_PREFIX + " proto: " + r.type);
        ctx.plate.add(OWNED_PREFIX + " src: " + r.source +
            (r.comment.isEmpty() ? "" : " // " + r.comment));
        Function f = ensureFunction(addr, block, log);
        if (f == null) {
            if (!log.errors.isEmpty()) {
                // no function can be made here: keep the name visible as a plain label
                ensureLabel(addr, r.name, false, AtDefaultFunction.SKIP, log);
                return;
            }
            // dry-run only: the function would be created (default name) and then renamed
            log.actions.add("name " + r.name);
            count("functions.renamed");
            functionsNamed.add(addr);
            checkSignature(r, log, ctx);
            return;
        }
        if (f.isThunk()) {
            // FunctionDB.updateFunction forwards a thunk's signature to the thunked function
            log.warnings.add("function at " + addr + " is a thunk: the name is set on the " +
                "thunk, Ghidra applies the prototype to the thunked function");
        }
        nameFunction(f, r, addr, ctx, log);
        FunctionDefinition fd = checkSignature(r, log, ctx);
        if (fd != null && !opts.dryRun) {
            applySignature(f, r, fd, log);
        }
    }

    private Function ensureFunction(Address addr, MemoryBlock block, RowLog log) {
        Function f = listing.getFunctionAt(addr);
        if (f != null) {
            return f;
        }
        if (listing.getInstructionAt(addr) == null) {
            Instruction containing = listing.getInstructionContaining(addr);
            if (containing != null) {
                log.errors.add("address is inside the instruction at " +
                    containing.getMinAddress() + "; function not created");
                return null;
            }
            Data d = listing.getDataContaining(addr);
            if (d != null && !Undefined.isUndefined(d.getDataType())) {
                log.errors.add("defined data '" + d.getDataType().getDisplayName() + "' at " +
                    d.getMinAddress() + "; function not created");
                return null;
            }
            if (!block.isInitialized() || !block.isExecute()) {
                log.errors.add("block " + block.getName() + " is not initialized executable " +
                    "memory; function not created");
                return null;
            }
            if (opts.dryRun) {
                log.actions.add("disassemble");
                log.actions.add("create function");
                count("functions.disassembled");
                count("functions.created");
                log.createdFunction = true;
                return null;
            }
            if (d != null && d.isDefined()) {
                // undefined1..8 / undefined array (checked above): clear it so that the
                // disassembler may use the bytes; DEFAULT bytes need no clearing
                listing.clearCodeUnits(d.getMinAddress(), d.getMaxAddress(), false);
            }
            if (!disassemble(addr) || listing.getInstructionAt(addr) == null) {
                log.errors.add("disassembly failed; function not created");
                return null;
            }
            count("functions.disassembled");
        }
        if (opts.dryRun) {
            log.actions.add("create function");
            count("functions.created");
            log.createdFunction = true;
            return null;
        }
        f = createFunction(addr, null);
        if (f == null) {
            log.errors.add("CreateFunctionCmd failed");
            return null;
        }
        count("functions.created");
        log.createdFunction = true;
        return f;
    }

    /** May the D2BS name replace a name of this source (names policy)? */
    private boolean canTakeOver(SourceType src) {
        if ("keep".equals(opts.names)) {
            return false;
        }
        if ("force".equals(opts.names)) {
            return true;
        }
        // SourceType.AI (Ghidra 12) ranks with ANALYSIS; compared by name so that the
        // script still compiles on versions without that constant
        return src == SourceType.DEFAULT || src == SourceType.ANALYSIS ||
            "AI".equals(src.name());
    }

    private void nameFunction(Function f, Row r, Address addr, AddrCtx ctx, RowLog log) {
        String cur = f.getName();
        if (cur.equals(r.name)) {
            count("functions.name-already");
            return;
        }
        SourceType src = f.getSymbol().getSource();
        // a function this run created has no name worth keeping, whatever the policy
        if (!log.createdFunction && !canTakeOver(src)) {
            if (src == SourceType.DEFAULT) {
                // names=keep on a FUN_* name: a label here would rename the function
                ctx.plate.add(OWNED_PREFIX + " note: existing name '" + cur + "' kept (names=" +
                    opts.names + "); no label added (it would rename this default-named function)");
            }
            else {
                ensureLabel(addr, r.name, false, AtDefaultFunction.SKIP, log);
                ctx.plate.add(OWNED_PREFIX + " note: existing name '" + cur + "' kept (names=" +
                    opts.names + "); D2BS name added as a secondary label");
            }
            count("functions.name-kept");
            return;
        }
        if (opts.dryRun) {
            log.actions.add("rename " + cur + " -> " + r.name);
            count("functions.renamed");
            functionsNamed.add(addr);
            return;
        }
        try {
            Symbol same = findSymbolAt(addr, r.name);
            if (same != null && same.getSymbolType() != SymbolType.FUNCTION) {
                same.delete();
            }
            f.setName(r.name, SourceType.USER_DEFINED);
            count("functions.renamed");
            functionsNamed.add(addr);
            if (src != SourceType.DEFAULT && findSymbolAt(addr, cur) == null) {
                symbolTable.createLabel(addr, cur, src);
            }
        }
        catch (Exception e) {
            log.errors.add("rename " + cur + " -> " + r.name + " failed: " + e.getMessage());
        }
    }

    /**
     * Normalizes and parses the prototype (also in dry-run). Returns the definition to
     * apply, or null if prototypes are skipped for this row or it did not parse.
     */
    private FunctionDefinition checkSignature(Row r, RowLog log, AddrCtx ctx) {
        if (opts.skipSignatures) {
            count("signatures.skipped");
            return null;
        }
        if (r.has("asm-only") && "skip".equals(opts.asmOnly)) {
            ctx.plate.add(OWNED_PREFIX + " note: asm-only: declared prototype not applied; " +
                "the asm stub defines the real ABI (docs/memory/call-stubs.md)");
            count("signatures.asm-only-skipped");
            return null;
        }
        String norm;
        try {
            norm = normalizePrototype(r.type, r.name, protoTypedefs);
            if (norm.contains("__thiscall")) {
                // C.jj has tokens for __cdecl/__stdcall/__fastcall/__vectorcall, not __thiscall
                throw new IllegalArgumentException("Ghidra's C parser has no __thiscall " +
                    "keyword; set this function's calling convention by hand");
            }
        }
        catch (IllegalArgumentException e) {
            log.errors.add("prototype: " + e.getMessage());
            count("signatures.failed");
            return null;
        }
        String problem;
        try {
            FunctionDefinition fd = parsePrototype(universe, norm, r.name);
            if (opts.dryRun) {
                log.actions.add("apply prototype " + norm);
                count("signatures.applied");
            }
            return fd;
        }
        catch (ParseException | RuntimeException e) {
            problem = firstLine(e.getMessage());
        }
        catch (Error e) {
            if (e instanceof VirtualMachineError) {
                throw e;
            }
            problem = e.toString(); // e.g. the C lexer's TokenMgrError
        }
        log.errors.add("prototype did not parse (" + problem + "): " + norm);
        count("signatures.failed");
        return null;
    }

    private void applySignature(Function f, Row r, FunctionDefinition fd, RowLog log) {
        try {
            // keep the function's (policy-decided) name: the command renames default names
            fd.setName(f.getName());
        }
        catch (Exception e) {
            log.errors.add("prototype: cannot set name: " + e.getMessage());
            count("signatures.failed");
            return;
        }
        ApplyFunctionSignatureCmd cmd =
            new ApplyFunctionSignatureCmd(f.getEntryPoint(), fd, SourceType.USER_DEFINED);
        if (!cmd.applyTo(currentProgram, monitor)) {
            log.errors.add("ApplyFunctionSignatureCmd failed: " + cmd.getStatusMsg());
            count("signatures.failed");
            return;
        }
        count("signatures.applied");
        String want = splitPrototype(r.type, r.name).cc;
        String got = f.getCallingConventionName();
        if (!want.isEmpty() && !want.equals(got)) {
            log.warnings.add("calling convention is '" + got + "', expected " + want);
            count("signatures.cc-mismatch");
        }
    }

    private void applyData(Row r, Address addr, MemoryBlock block, AddrCtx ctx, RowLog log) {
        // a DATA row at a FUN_* entry is a conflict: never rename the function after it
        ensureLabel(addr, r.name, !r.isAlias(), AtDefaultFunction.SKIP, log);
        ctx.eol.add(rowLine(r));
        if (r.isAlias()) {
            return;
        }
        if (r.type.isEmpty()) {
            count("data.untyped");
            return;
        }
        DataTypeManager typeSource = opts.dryRun ? universe : programDtm;
        if (typeSource == null) {
            log.warnings.add("data type '" + r.type + "': no type source; label only");
            count("data.type-missing");
            return;
        }
        DataType dt;
        try {
            dt = resolveDataType(typeSource, r.type);
        }
        catch (IllegalArgumentException e) {
            log.warnings.add("data type: " + e.getMessage() + "; label only");
            count("data.type-missing");
            return;
        }
        if (dt == null) {
            log.warnings.add("data type '" + r.type + "' not found under " + D2BS_CATEGORY +
                "; label only");
            count("data.type-missing");
            return;
        }
        int len = dt.getLength();
        if (len <= 0) {
            log.warnings.add("data type '" + r.type + "' has no fixed size; label only");
            count("data.type-missing");
            return;
        }
        Address end;
        try {
            end = addr.addNoWrap(len - 1);
        }
        catch (AddressOverflowException e) {
            log.warnings.add("data type '" + r.type + "' overflows the address space");
            count("data.conflict");
            return;
        }
        if (!block.contains(end)) {
            log.warnings.add("data type '" + r.type + "' (" + len + " bytes) extends past " +
                "block " + block.getName() + "; label only");
            count("data.conflict");
            return;
        }
        Data existing = listing.getDataAt(addr);
        if (existing != null && !Undefined.isUndefined(existing.getDataType()) &&
            existing.getDataType().isEquivalent(dt)) {
            count("data.already");
            return;
        }
        String conflict = findConflict(addr, end);
        if (conflict != null) {
            log.warnings.add("data type '" + r.type + "' not applied: " + conflict +
                " (never overwritten)");
            count("data.conflict");
            return;
        }
        if (opts.dryRun) {
            log.actions.add("apply data type " + r.type);
            count("data.applied");
            return;
        }
        try {
            listing.clearCodeUnits(addr, end, false);
            listing.createData(addr, dt);
            count("data.applied");
        }
        catch (Exception e) {
            log.errors.add("createData(" + r.type + ") failed: " + e.getMessage());
        }
    }

    /** First instruction or defined (non-undefined) data in [start, end], or null. */
    private String findConflict(Address start, Address end) {
        Address a = start;
        while (a != null && a.compareTo(end) <= 0) {
            CodeUnit cu = listing.getCodeUnitContaining(a);
            if (cu == null) {
                a = a.next();
                continue;
            }
            if (cu instanceof Instruction) {
                return "instruction at " + cu.getMinAddress();
            }
            if (cu instanceof Data) {
                DataType t = ((Data) cu).getDataType();
                if (!Undefined.isUndefined(t)) {
                    return "defined data '" + t.getDisplayName() + "' at " + cu.getMinAddress();
                }
            }
            a = cu.getMaxAddress().next();
        }
        return null;
    }

    private void applyPatch(Row r, Address addr, AddrCtx ctx, RowLog log) {
        // patch sites at a FUN_* entry get no label: it would rename the game function after
        // the patch (bookmark and pre-comment carry the name)
        ensureLabel(addr, r.name, false, AtDefaultFunction.SKIP_QUIETLY, log);
        String suffix = null;
        Row target = rowsByName.get(r.extraMap.get("target"));
        if (target != null && target.rva >= 0) {
            try {
                suffix = " (" + imageBase.addNoWrap(target.rva) + ")";
            }
            catch (AddressOverflowException e) {
                suffix = null;
            }
        }
        String line = patchLine(r, suffix);
        ctx.pre.add(line);
        ctx.pre.add(OWNED_PREFIX + " patch src: " + r.name + " " + r.source + " [" +
            r.flagText() + "]" + (r.comment.isEmpty() ? "" : " // " + r.comment));
        if (r.has("captured-encoded")) {
            ctx.pre.add(OWNED_PREFIX + " patch note: captured-encoded: Patch.h reads the " +
                "target before DefineOffsets() runs, so the installed jump goes to its " +
                "DLLOFFSET encoding, not to the address above (docs/memory/README.md 5.1)");
        }
        String note = r.name + ": " + line.substring((OWNED_PREFIX + " patch: ").length()) +
            " (" + r.source + ")";
        if (!"BYTES".equals(r.type)) {
            String check = checkPatchSite(addr, r.patchLength());
            if (check != null) {
                ctx.pre.add(OWNED_PREFIX + " patch check: " + check);
                log.warnings.add("patch site: " + check);
                note += " CHECK: " + check;
                count("patches.check-failed");
            }
            else {
                count("patches.check-ok");
            }
        }
        ctx.notes.add(note);
    }

    /** CALL/JMP sites must start and end on instruction boundaries. Read-only. */
    private String checkPatchSite(Address addr, int len) {
        Instruction ins = listing.getInstructionAt(addr);
        if (ins == null) {
            Instruction c = listing.getInstructionContaining(addr);
            return c != null ? "site is inside the instruction at " + c.getMinAddress()
                    : "no instruction at the site (not disassembled)";
        }
        int covered = 0;
        Instruction cur = ins;
        while (cur != null && covered < len) {
            covered += cur.getLength();
            Address next = cur.getMaxAddress().next();
            cur = next == null ? null : listing.getInstructionAt(next);
        }
        if (covered < len) {
            return "only " + covered + " of the " + len + " patched bytes are instructions";
        }
        if (covered != len) {
            return "the " + len + " patched bytes end inside an instruction (next boundary at +" +
                covered + ")";
        }
        return null;
    }

    private Symbol findSymbolAt(Address addr, String name) {
        for (Symbol s : symbolTable.getSymbols(addr)) {
            if (s.getName().equals(name)) {
                return s;
            }
        }
        return null;
    }

    /**
     * What {@link #ensureLabel} does where a function with a default name (FUN_*) starts:
     * SymbolTable.createLabel does not add a label there but renames that function
     * (SymbolManager.tryUpdatingDefaultFunction, Ghidra 10.x to 12.x).
     */
    private enum AtDefaultFunction {
        /** let createLabel name the function (LABEL rows, names=auto|force) */
        RENAME,
        /** create no label, log a warning (stale, alias and DATA rows, names=keep) */
        SKIP,
        /** create no label, count only (patch rows: the patch is not the function's name) */
        SKIP_QUIETLY
    }

    /**
     * Creates label {@code name} at {@code addr} unless a symbol of that name is already
     * there. With {@code primaryIfAllowed} the label becomes primary when the current
     * primary symbol may be taken over (names policy); never over a function symbol.
     * {@code atDefault} decides what happens at the entry of a default-named function.
     */
    private void ensureLabel(Address addr, String name, boolean primaryIfAllowed,
            AtDefaultFunction atDefault, RowLog log) {
        if (findSymbolAt(addr, name) == null) {
            Function fn = listing.getFunctionAt(addr);
            // functionsNamed: in dry-run the earlier row's rename has not really happened
            if (fn != null && fn.getSymbol().getSource() == SourceType.DEFAULT &&
                !functionsNamed.contains(addr)) {
                if (atDefault != AtDefaultFunction.RENAME) {
                    count("labels.default-function-skipped");
                    if (atDefault == AtDefaultFunction.SKIP) {
                        log.warnings.add("label " + name + " not created: the default-named " +
                            "function " + fn.getName() + " starts here and a label would rename " +
                            "it; the name is only in the comment");
                    }
                    return;
                }
                functionsNamed.add(addr);
                if (opts.dryRun) {
                    log.actions.add("name function " + fn.getName() + " -> " + name);
                    count("labels.default-function-named");
                    return;
                }
                try {
                    symbolTable.createLabel(addr, name, SourceType.USER_DEFINED);
                    count("labels.default-function-named");
                }
                catch (Exception e) {
                    log.errors.add("label " + name + " failed: " + e.getMessage());
                }
                return;
            }
        }
        Symbol prim = symbolTable.getPrimarySymbol(addr);
        boolean wantPrimary = primaryIfAllowed &&
            (prim == null || prim.isDynamic() ||
                (prim.getSymbolType() != SymbolType.FUNCTION && canTakeOver(prim.getSource())));
        Symbol existing = findSymbolAt(addr, name);
        if (existing != null) {
            if (wantPrimary && !existing.isPrimary()) {
                if (opts.dryRun) {
                    log.actions.add("make label " + name + " primary");
                    count("labels.made-primary");
                }
                else if (existing.setPrimary()) {
                    count("labels.made-primary");
                }
            }
            count("labels.existing");
            return;
        }
        if (opts.dryRun) {
            log.actions.add("label " + name + (wantPrimary ? " (primary)" : ""));
            count("labels.created");
            if (wantPrimary && prim != null && !prim.isDynamic()) {
                count("labels.made-primary");
            }
            return;
        }
        try {
            Symbol s = symbolTable.createLabel(addr, name, SourceType.USER_DEFINED);
            count("labels.created");
            if (wantPrimary && !s.isPrimary() && s.setPrimary()) {
                count("labels.made-primary");
            }
        }
        catch (Exception e) {
            log.errors.add("label " + name + " failed: " + e.getMessage());
        }
    }

    /**
     * Writes the collected bookmarks (at each row address) and comments. FlatProgramAPI's
     * set*Comment (SetCommentCmd) stores a comment on the code unit that CONTAINS the address
     * (for data: the primitive component there), while get*Comment reads the record at exactly
     * the address. Comments are therefore keyed by {@link #commentAddress}: rows whose address is
     * inside an instruction or a data primitive share the comment of that code unit, with their
     * lines tagged "D2BS @addr". Reading and writing the same address keeps re-runs idempotent
     * and never discards text the script does not own.
     */
    private void writeAnnotations() {
        Map<Address, AddrCtx> byCommentAddr = new LinkedHashMap<>();
        for (Pending p : pending) {
            try {
                writeBookmark(p.addr, BookmarkType.NOTE, p.ctx.notes);
                writeBookmark(p.addr, BookmarkType.WARNING, p.ctx.warns);
            }
            catch (RuntimeException e) {
                error("bookmarks at " + p.addr + ": unexpected " + e);
            }
            Address ca;
            try {
                ca = commentAddress(p.addr);
            }
            catch (RuntimeException e) {
                ca = null;
            }
            if (ca == null) {
                if (p.ctx.hasComments()) {
                    warn("no code unit holds comments at " + p.addr + "; comments not written");
                }
                continue;
            }
            byCommentAddr.computeIfAbsent(ca, k -> new AddrCtx())
                    .addCommentsFrom(p.ctx, ca.equals(p.addr) ? null : p.addr.toString());
            if (!ca.equals(p.addr) && p.ctx.hasComments()) {
                count("comments.offcut-rows");
            }
        }
        for (Map.Entry<Address, AddrCtx> e : byCommentAddr.entrySet()) {
            Address a = e.getKey();
            AddrCtx ctx = e.getValue();
            try {
                writeComment(a, "plate", ctx.plate);
                writeComment(a, "pre", ctx.pre);
                writeComment(a, "eol", ctx.eol);
            }
            catch (RuntimeException ex) {
                error("comments at " + a + ": unexpected " + ex);
            }
        }
    }

    /**
     * The address whose comment record SetCommentCmd writes for {@code addr}: the start of the
     * code unit containing it, or for data the start of the primitive component at that
     * offset. Null if there is none (SetCommentCmd would then fail).
     */
    private Address commentAddress(Address addr) {
        CodeUnit cu = listing.getCodeUnitContaining(addr);
        if (cu == null) {
            return null;
        }
        Address min = cu.getMinAddress();
        if (min.equals(addr)) {
            return addr;
        }
        if (cu instanceof Data) {
            Data prim = ((Data) cu).getPrimitiveAt((int) addr.subtract(min));
            return prim == null ? null : prim.getMinAddress();
        }
        return min;
    }

    private void writeComment(Address addr, String kind, List<String> ours) {
        String existing;
        switch (kind) {
            case "plate":
                existing = getPlateComment(addr);
                break;
            case "pre":
                existing = getPreComment(addr);
                break;
            default:
                existing = getEOLComment(addr);
                break;
        }
        boolean hadOwned = false;
        if (existing != null) {
            for (String l : existing.split("\n", -1)) {
                hadOwned |= isOwnedLine(l);
            }
        }
        if (ours.isEmpty() && !hadOwned) {
            return;
        }
        String merged = mergeOwnedLines(existing, ours);
        if (merged == null ? existing == null : merged.equals(existing)) {
            return;
        }
        count("comments." + kind);
        if (opts.dryRun) {
            return;
        }
        boolean ok;
        switch (kind) {
            case "plate":
                ok = setPlateComment(addr, merged);
                break;
            case "pre":
                ok = setPreComment(addr, merged);
                break;
            default:
                ok = setEOLComment(addr, merged);
                break;
        }
        if (!ok) {
            error(kind + " comment at " + addr + " could not be set (no code unit)");
        }
    }

    /**
     * Sets (or replaces: one bookmark per address, type and category) the D2BS bookmark of
     * {@code type}; removes it when the rows at this address no longer call for one.
     */
    private void writeBookmark(Address addr, String type, List<String> texts) {
        Bookmark old = bookmarks.getBookmark(addr, type, BOOKMARK_CATEGORY);
        if (texts.isEmpty()) {
            if (old != null) {
                count("bookmarks.removed");
                if (!opts.dryRun) {
                    bookmarks.removeBookmark(old);
                }
            }
            return;
        }
        String text = String.join(" | ", texts);
        if (old != null && text.equals(old.getComment())) {
            count("bookmarks.unchanged");
            return;
        }
        count("bookmarks." + type.toLowerCase(Locale.ROOT));
        if (!opts.dryRun) {
            bookmarks.setBookmark(addr, type, BOOKMARK_CATEGORY, text);
        }
    }

    /** Records the row outcome: skipped, failed (any error) or applied. */
    private void finish(RowLog log) {
        int[] s = kindStats.get(log.row.kind);
        String head = log.row.kind + " " + log.row.name + " @" + log.where + " (" +
            log.row.source + "): ";
        if (log.skipReason != null) {
            s[1]++;
            warn(head + "skipped: " + log.skipReason);
        }
        else if (!log.errors.isEmpty()) {
            s[2]++;
            for (String e : log.errors) {
                error(head + e);
            }
        }
        else {
            s[0]++;
        }
        for (String w : log.warnings) {
            warn(head + w);
        }
        if (opts.dryRun && !log.actions.isEmpty()) {
            println("[dry-run] " + head + String.join("; ", log.actions));
        }
    }

    // ------------------------------------------------------------------------------------
    // Summary
    // ------------------------------------------------------------------------------------

    private void printSummary(List<Row> rows, boolean cancelled) {
        StringBuilder b = new StringBuilder();
        b.append("D2BSImport summary").append(opts.dryRun
                ? " (dry run: nothing was changed; counts are what a real run would do)"
                : "").append(cancelled
                ? " (CANCELLED: rows after the cancel were not processed and no comment or " +
                    "bookmark was written; changes made so far are kept, Undo reverts the run)"
                : "").append('\n');
        b.append(String.format("  %-11s %6s %8s %8s %7s%n", "kind", "rows", "applied", "skipped",
            "failed"));
        int[] tot = new int[4];
        for (Map.Entry<String, int[]> e : kindStats.entrySet()) {
            int[] s = e.getValue();
            int n = 0;
            for (Row r : rows) {
                n += r.kind.equals(e.getKey()) ? 1 : 0;
            }
            b.append(String.format("  %-11s %6d %8d %8d %7d%n", e.getKey(), n, s[0], s[1], s[2]));
            tot[0] += n;
            tot[1] += s[0];
            tot[2] += s[1];
            tot[3] += s[2];
        }
        b.append(String.format("  %-11s %6d %8d %8d %7d%n", "total", tot[0], tot[1], tot[2],
            tot[3]));
        b.append(String.format("  types: parsed %d, new %d, equivalent %d, conflicting %d%n",
            counter("types.parsed"), counter("types.new"), counter("types.equivalent"),
            counter("types.conflicting")));
        b.append(String.format("  functions: created %d (disassembled %d), renamed %d, " +
            "already named %d, existing name kept %d%n", counter("functions.created"),
            counter("functions.disassembled"), counter("functions.renamed"),
            counter("functions.name-already"), counter("functions.name-kept")));
        b.append(String.format("  prototypes: applied %d, failed %d, asm-only not applied %d, " +
            "skipped %d, aliases %d, calling-convention mismatches %d%n",
            counter("signatures.applied"), counter("signatures.failed"),
            counter("signatures.asm-only-skipped"), counter("signatures.skipped"),
            counter("signatures.alias"), counter("signatures.cc-mismatch")));
        b.append(String.format("  labels: created %d, already present %d, made primary %d, " +
            "default-named functions named by a LABEL row %d, not created at a default-named " +
            "function %d; stale rows marked only %d%n", counter("labels.created"),
            counter("labels.existing"), counter("labels.made-primary"),
            counter("labels.default-function-named"), counter("labels.default-function-skipped"),
            counter("stale.marked")));
        b.append(String.format("  data types: applied %d, already applied %d, not applied " +
            "(conflict) %d, type unknown %d, untyped rows %d%n", counter("data.applied"),
            counter("data.already"), counter("data.conflict"), counter("data.type-missing"),
            counter("data.untyped")));
        b.append(String.format("  patch sites: boundary check ok %d, failed %d%n",
            counter("patches.check-ok"), counter("patches.check-failed")));
        b.append(String.format("  comments changed: plate %d, pre %d, eol %d (rows inside a " +
            "code unit, commented on it: %d); bookmarks set: note %d, warning %d, unchanged %d, " +
            "removed %d%n", counter("comments.plate"), counter("comments.pre"),
            counter("comments.eol"), counter("comments.offcut-rows"), counter("bookmarks.note"),
            counter("bookmarks.warning"), counter("bookmarks.unchanged"),
            counter("bookmarks.removed")));
        appendList(b, "errors", errors);
        appendList(b, "warnings", warnings);
        println(b.toString());
    }

    private void appendList(StringBuilder b, String title, List<String> items) {
        int shown = Math.min(items.size(), opts.maxErrors);
        b.append("  ").append(title).append(": ").append(items.size());
        if (shown < items.size()) {
            b.append(" (first ").append(shown).append(" shown)");
        }
        b.append('\n');
        for (int i = 0; i < shown; i++) {
            b.append("    - ").append(items.get(i)).append('\n');
        }
    }
}
