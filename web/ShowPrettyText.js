import { app } from "../../../scripts/app.js";
import { ComfyWidgets } from "../../../scripts/widgets.js";

app.registerExtension({
    name: "CaseReview.ShowPrettyText",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name === "ShowPrettyText") {
            function populate(text) {
                if (this.widgets) {
                    // 清除旧的小部件
                    for (let i = 1; i < this.widgets.length; i++) {
                        this.widgets[i].onRemove?.();
                    }
                    this.widgets.length = 1;
                }

                // 创建显示文本的小部件
                const widget = ComfyWidgets["STRING"](
                    this, 
                    "pretty_text", 
                    ["STRING", { multiline: true }], 
                    app
                ).widget;

                // 设置小部件属性
                widget.inputEl.readOnly = true;
                widget.inputEl.style.opacity = 0.8;
                widget.inputEl.style.fontFamily = "monospace";
                widget.value = text[0] || "";

                // 调整节点大小
                requestAnimationFrame(() => {
                    const sz = this.computeSize();
                    sz[0] = 400;  // 固定宽度
                    sz[1] = Math.max(200, this.computeSize()[1]);  // 最小高度200
                    this.onResize?.(sz);
                    app.graph.setDirtyCanvas(true, false);
                });
            }

            // 节点执行时更新显示
            const onExecuted = nodeType.prototype.onExecuted;
            nodeType.prototype.onExecuted = function (message) {
                onExecuted?.apply(this, arguments);
                populate.call(this, message.text);
            };

            // 节点配置时初始化显示
            const onConfigure = nodeType.prototype.onConfigure;
            nodeType.prototype.onConfigure = function () {
                onConfigure?.apply(this, arguments);
                if (this.widgets_values?.length) {
                    populate.call(this, [this.widgets_values[0]]);
                }
            };
        }
    },
});
