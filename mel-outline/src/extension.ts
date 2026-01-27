import * as vscode from 'vscode';

// ========================================================
// 正则表达式定义
// ========================================================

// 1. 用于查找定义的正则 (用来在大纲和跳转中使用)
const PROC_DEF_REGEX = /^\s*(?:global\s+)?proc\s+(?:.+?\s+)?(\w+)\s*\(/;

// 2. 用于导出完整签名的正则
const EXPORT_SIGNATURE_REGEX = /^\s*((?:global\s+)?proc\s+(?:.+?\s+)?(\w+)\s*\(.*?\))/;

export function activate(context: vscode.ExtensionContext) {
    const MEL_SELECTOR = { language: 'mel' };

    // 1. 跳转到定义 (Go to Definition)
    context.subscriptions.push(vscode.languages.registerDefinitionProvider(MEL_SELECTOR, new MelDefinitionProvider()));
    
    // 2. 引用计数显示 (CodeLens) - 显示在函数头上
    context.subscriptions.push(vscode.languages.registerCodeLensProvider(MEL_SELECTOR, new MelCodeLensProvider()));
    
    // 3. 查找引用 (Find All References) - 点击 CodeLens 后调用的核心逻辑 <--- 新增
    context.subscriptions.push(vscode.languages.registerReferenceProvider(MEL_SELECTOR, new MelReferenceProvider()));

    // 4. 代码折叠
    context.subscriptions.push(vscode.languages.registerFoldingRangeProvider(MEL_SELECTOR, new MelFoldingProvider()));
    
    // 5. 大纲支持
    context.subscriptions.push(vscode.languages.registerDocumentSymbolProvider(MEL_SELECTOR, new MelDocumentSymbolProvider()));
    
    // 6. 注册导出命令
    context.subscriptions.push(vscode.commands.registerCommand('mel-outline.exportGlobalProcs', exportGlobalProcs));
}

export function deactivate() {}

// ========================================================
// 新增核心功能：引用查找提供者
// ========================================================
class MelReferenceProvider implements vscode.ReferenceProvider {
    provideReferences(
        document: vscode.TextDocument, 
        position: vscode.Position, 
        context: vscode.ReferenceContext, 
        token: vscode.CancellationToken
    ): vscode.ProviderResult<vscode.Location[]> {
        
        const locations: vscode.Location[] = [];
        
        // 1. 获取当前光标选中的单词 (函数名)
        const wordRange = document.getWordRangeAtPosition(position);
        if (!wordRange) return locations;
        const word = document.getText(wordRange);

        // 2. 构造全字匹配正则
        // 比如查找 "myFunc"，正则为 /\bmyFunc\b/g
        const regex = new RegExp(`\\b${word}\\b`, 'g');

        // 3. 扫描全文查找匹配项
        for (let i = 0; i < document.lineCount; i++) {
            const line = document.lineAt(i);
            const text = line.text;

            // 在当前行中查找所有出现的位置
            let match;
            while ((match = regex.exec(text)) !== null) {
                const startPos = new vscode.Position(i, match.index);
                const endPos = new vscode.Position(i, match.index + word.length);
                const range = new vscode.Range(startPos, endPos);
                
                locations.push(new vscode.Location(document.uri, range));
            }
        }

        return locations;
    }
}

// ========================================================
// 功能：跳转到定义
// ========================================================
class MelDefinitionProvider implements vscode.DefinitionProvider {
    provideDefinition(document: vscode.TextDocument, position: vscode.Position, token: vscode.CancellationToken): vscode.ProviderResult<vscode.Location> {
        const range = document.getWordRangeAtPosition(position);
        if (!range) return null;
        const word = document.getText(range);
        for (let i = 0; i < document.lineCount; i++) {
            const line = document.lineAt(i);
            const match = PROC_DEF_REGEX.exec(line.text);
            if (match && match[1] === word) {
                return new vscode.Location(document.uri, line.range);
            }
        }
        return null;
    }
}

// ========================================================
// 功能：引用计数 (CodeLens)
// ========================================================
class MelCodeLensProvider implements vscode.CodeLensProvider {
    provideCodeLenses(document: vscode.TextDocument, token: vscode.CancellationToken): vscode.ProviderResult<vscode.CodeLens[]> {
        const codeLenses: vscode.CodeLens[] = [];
        const text = document.getText();
        
        for (let i = 0; i < document.lineCount; i++) {
            const line = document.lineAt(i);
            const match = PROC_DEF_REGEX.exec(line.text);
            
            if (match) {
                const funcName = match[1];
                const range = line.range;

                // 计算引用次数
                const regex = new RegExp(`\\b${funcName}\\b`, 'g');
                const matches = text.match(regex);
                
                // 减去 1 (定义本身不算引用)
                // 如果结果 < 0 (理论不可能)，归 0
                const count = matches ? Math.max(0, matches.length - 1) : 0;
                
                const title = count === 1 ? '1 reference' : `${count} references`;

                // 核心改动：
                // 当引用数 > 0 时，绑定命令 'editor.action.referenceSearch.trigger'
                // 因为我们上面注册了 MelReferenceProvider，这个命令现在生效了！
                const command: vscode.Command = {
                    title: title,
                    command: count > 0 ? 'editor.action.referenceSearch.trigger' : '',
                    arguments: []
                };

                codeLenses.push(new vscode.CodeLens(range, command));
            }
        }
        return codeLenses;
    }
}

// ========================================================
// 功能：代码折叠
// ========================================================
class MelFoldingProvider implements vscode.FoldingRangeProvider {
    provideFoldingRanges(document: vscode.TextDocument, context: vscode.FoldingContext, token: vscode.CancellationToken): vscode.ProviderResult<vscode.FoldingRange[]> {
        const ranges: vscode.FoldingRange[] = [];
        const stack: number[] = [];
        for (let i = 0; i < document.lineCount; i++) {
            const text = document.lineAt(i).text;
            if (text.trim().startsWith('//')) continue;
            for (let char of text) {
                if (char === '{') stack.push(i);
                else if (char === '}') {
                    if (stack.length > 0) {
                        const start = stack.pop();
                        if (start !== undefined && start !== i) ranges.push(new vscode.FoldingRange(start, i));
                    }
                }
            }
        }
        return ranges;
    }
}

// ========================================================
// 功能：大纲支持
// ========================================================
class MelDocumentSymbolProvider implements vscode.DocumentSymbolProvider {
    public provideDocumentSymbols(document: vscode.TextDocument, token: vscode.CancellationToken): vscode.ProviderResult<vscode.DocumentSymbol[]> {
        const symbols: vscode.DocumentSymbol[] = [];
        for (let i = 0; i < document.lineCount; i++) {
            const line = document.lineAt(i);
            if (line.isEmptyOrWhitespace) continue;
            const match = PROC_DEF_REGEX.exec(line.text);
            if (match) {
                const isGlobal = line.text.includes("global");
                const symbol = new vscode.DocumentSymbol(
                    match[1],
                    isGlobal ? 'global proc' : 'proc',
                    vscode.SymbolKind.Function,
                    line.range,
                    line.range
                );
                symbols.push(symbol);
            }
        }
        return symbols;
    }
}

// ========================================================
// 功能：导出 Proc 命令
// ========================================================
async function exportGlobalProcs() {
    const editor = vscode.window.activeTextEditor;
    if (!editor) {
        vscode.window.showErrorMessage('请先打开一个 MEL 文件！');
        return;
    }

    const document = editor.document;
    const fullText = document.getText(); 
    const validProcs: string[] = [];

    for (let i = 0; i < document.lineCount; i++) {
        const line = document.lineAt(i);
        const text = line.text;
        
        if (text.trim().startsWith('//')) continue;

        const match = EXPORT_SIGNATURE_REGEX.exec(text);

        if (match) {
            const fullSignature = match[1].trim(); 
            const funcName = match[2];             

            const refRegex = new RegExp(`\\b${funcName}\\b`, 'g');
            const matches = fullText.match(refRegex);
            
            if (matches && matches.length > 1) {
                validProcs.push(fullSignature + ";");
            }
        }
    }

    if (validProcs.length === 0) {
        vscode.window.showInformationMessage('未找到被引用的 global proc (引用计数 > 0)。');
        return;
    }

    const header = `// =============================================\n` + 
                   `// Exported Procs from: ${document.fileName}\n` + 
                   `// Filter: Reference Count > 0\n` +
                   `// Total: ${validProcs.length}\n` +
                   `// =============================================\n\n`;
                   
    const content = header + validProcs.join('\n');

    const newDoc = await vscode.workspace.openTextDocument({
        content: content,
        language: 'mel'
    });
    await vscode.window.showTextDocument(newDoc);
}