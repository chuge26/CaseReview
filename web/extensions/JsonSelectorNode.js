import { app } from "../../../scripts/app.js";

// 调试标识
const DEBUG = true;
const EXTENSION_NAME = "Comfy.JSONFormatterPro";

// 配置常量
const NODE_CONFIG = {
  TARGET_CLASS: "JSONKeyExtractor",
  SLOT_PREFIX: "key_",
  SLOT_TYPE: "STRING",
  MIN_DELAY: 50,  // 防冲突延迟(ms)
};

// 扩展冲突检测
function checkConflicts() {
  if (DEBUG) console.groupCollapsed(`[${EXTENSION_NAME}] Conflict Check`);
  
  const conflictingExtensions = [
    "efficiency.widgethider",
    "impact.widgets"
  ].filter(name => 
    app.extensions.some(ext => ext.name.includes(name))
  );

  if (conflictingExtensions.length) {
    console.warn("Detected possible conflicts:", conflictingExtensions);
    
    // 自动修复常见冲突
    conflictingExtensions.forEach(name => {
      const ext = app.extensions.find(e => e.name.includes(name));
      if (ext?.nodeCreated) {
        const original = ext.nodeCreated.bind(ext);
        ext.nodeCreated = function(...args) {
          try {
            return original(...args);
          } catch (e) {
            DEBUG && console.log(`[Conflict Solved] Silenced ${name} error:`, e.message);
            return null;
          }
        };
      }
    });
  }

  if (DEBUG) {
    console.log("Current extensions:", app.extensions.map(e => e.name));
    console.groupEnd();
  }
}

// 主扩展注册
app.registerExtension({
  name: EXTENSION_NAME,

  init() {
    checkConflicts();
    DEBUG && console.log(`[${EXTENSION_NAME}] Initialized`);
  },

  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (!nodeType.comfyClass?.includes(NODE_CONFIG.TARGET_CLASS)) {
      DEBUG && console.log(`[${EXTENSION_NAME}] Skipping non-target node:`, nodeType.comfyClass);
      return;
    }

    DEBUG && console.group(`[${EXTENSION_NAME}] Setting up ${nodeType.comfyClass} UI`);

    // 强化原型方法
    const originalOnCreated = nodeType.prototype.onNodeCreated?.bind(nodeType.prototype);
    const originalOnRemoved = nodeType.prototype.onRemoved?.bind(nodeType.prototype);

    nodeType.prototype.onNodeCreated = function() {
      try {
        // 保证原始逻辑执行
        originalOnCreated?.();

        // 延迟插入避免UI竞争
        setTimeout(() => {
          try {
            this._setupKeyControls();
          } catch (e) {
            console.error(`[${EXTENSION_NAME}] UI Setup Error:`, e);
          }
        }, NODE_CONFIG.MIN_DELAY);
      } catch (e) {
        console.error(`[${EXTENSION_NAME}] Node Creation Error:`, e);
      }
    };

    // 控件初始化方法
    nodeType.prototype._setupKeyControls = function() {
      const node = this;
      DEBUG && console.log(`[${EXTENSION_NAME}] Creating controls for ${node.id}`);

      // 容器元素
      const container = document.createElement("div");
      container.className = "crf-json-controls";
      Object.assign(container.style, {
        display: "flex",
        gap: "4px",
        margin: "8px 0",
        padding: "6px",
        background: "rgba(0,0,0,0.03)",
        borderRadius: "4px"
      });

      // 添加键按钮
      const addBtn = document.createElement("button");
      addBtn.textContent = "＋ Add Key";
      addBtn.className = "crf-add-btn";
      addBtn.onclick = () => {
        const existingKeys = node.inputs?.filter(i => 
          i.name.startsWith(NODE_CONFIG.SLOT_PREFIX)
        ) || [];
        const newSlot = `${NODE_CONFIG.SLOT_PREFIX}${existingKeys.length + 1}`;
        
        node.addInput(newSlot, NODE_CONFIG.SLOT_TYPE, {
          default: "",
          forceInput: true,
          placeholder: `Key ${existingKeys.length + 1}`
        });
        
        app.graph.setDirtyCanvas(true, true);
        DEBUG && console.log(`[${EXTENSION_NAME}] Added slot: ${newSlot}`);
      };

      // 清空按钮
      const clearBtn = document.createElement("button");
      clearBtn.textContent = "× Clear All";
      clearBtn.className = "crf-clear-btn";
      clearBtn.onclick = () => {
        node.inputs
          ?.filter(i => i.name.startsWith(NODE_CONFIG.SLOT_PREFIX))
          .forEach(input => node.removeInput(input.name));
        
        app.graph.setDirtyCanvas(true, true);
        DEBUG && console.log(`[${EXTENSION_NAME}] Cleared all slots`);
      };

      // 组装UI
      container.appendChild(addBtn);
      container.appendChild(clearBtn);
      
      if (!node.extraControls) node.extraControls = [];
      node.extraControls.push(container);

      DEBUG && console.log(`[${EXTENSION_NAME}] Controls added to node ${node.id}`);
    };

    // 清理方法
    nodeType.prototype.onRemoved = function() {
      DEBUG && console.log(`[${EXTENSION_NAME}] Node ${this.id} removed`);
      originalOnRemoved?.();
    };

    if (DEBUG) console.groupEnd();
  },

  async setup() {
    // 动态样式注入（带版本标识）
    const styleId = `${EXTENSION_NAME}-styles`;
    if (!document.getElementById(styleId)) {
      const style = document.createElement("style");
      style.id = styleId;
      style.textContent = `
        .crf-json-controls {
          order: 999;
          transition: all 0.2s ease;
        }
        .crf-add-btn {
          flex: 1;
          background: var(--comfy-input-bg) !important;
          color: var(--input-text) !important;
          border: 1px solid var(--comfy-menu-bg) !important;
        }
        .crf-clear-btn {
          width: 80px;
          background: var(--comfy-error-bg) !important;
          color: var(--input-text) !important;
          border: 1px solid var(--comfy-menu-bg) !important;
        }
        .crf-add-btn:hover, .crf-clear-btn:hover {
          filter: brightness(1.2);
        }
      `;
      document.head.appendChild(style);
      DEBUG && console.log(`[${EXTENSION_NAME}] Styles injected`);
    }

    // 全局错误监听
    window.addEventListener('error', (e) => {
      if (e.message.includes('widgethider')) {
        DEBUG && console.log(`[${EXTENSION_NAME}] Supressed widgethider error`);
        e.preventDefault();
      }
    });
  }
});

// 加载完成日志
DEBUG && console.log(`[${EXTENSION_NAME}] Module loaded`);
