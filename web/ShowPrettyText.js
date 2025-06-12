import { app } from "../../../scripts/app.js";
import { ComfyWidgets } from "../../../scripts/widgets.js";

app.registerExtension({
    name: "Comfy.ShowPrettyText",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name === "ShowPrettyText") {
            const onExecuted = nodeType.prototype.onExecuted;
            
            nodeType.prototype.onExecuted = function(message) {
                onExecuted?.apply(this, arguments);

                console.log("ShowPrettyText executed", message);

                console.log("this.widgets", this.widgets);
                
                // 清除旧控件
                while (this.widgets.length > 2) {
                    this.widgets[this.widgets.length - 1].onRemove?.();
                    this.widgets.pop();
                }
                
                // 添加结果显示控件
                const resultWidget = ComfyWidgets.STRING(this, "result", 
                    ["STRING", { multiline: true }], app).widget;

                console.log("resultWidget", resultWidget)
                resultWidget.inputEl.readOnly = true;
                resultWidget.inputEl.style.fontFamily = "monospace";
                resultWidget.value = message.text?.[0] || "";
                
                // 添加类型显示控件
                const typeWidget = ComfyWidgets.STRING(this, "result_type", 
                    ["STRING", { multiline: true }], app).widget;

                console.log("typeWidget", typeWidget);
                typeWidget.inputEl.readOnly = true;
                typeWidget.inputEl.style.fontStyle = "italic";
                typeWidget.inputEl.style.opacity = 0.7;
                typeWidget.value = message.type?.[0] || "";
                
                
                // 调整节点大小
                setTimeout(() => {
                    const sz = this.computeSize();
                    sz[0] = Math.max(sz[0], 300); // 最小宽度
                    sz[1] = Math.max(sz[1], 200); // 最小高度
                    this.onResize?.(sz);
                    app.graph.setDirtyCanvas(true, false);
                }, 0);
            };
            
            // 保持工作流加载时的显示
            const onConfigure = nodeType.prototype.onConfigure;
            nodeType.prototype.onConfigure = function() {
                onConfigure?.apply(this, arguments);
                if (this.widgets_values?.length >= 2) {
                    this.onExecuted({
                        text: [this.widgets_values[0]],
                        type: [this.widgets_values[1]]
                    });
                }
            };
        }
    }
});
