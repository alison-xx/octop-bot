/*! Generated from antd-mini@3.4.3 (MIT). See antd-mini.LICENSE.txt. */
(() => {
  // node_modules/antd-mini/es/Button/index.sjs
  function getClass(size) {
    var list = ["small", "medium", "large"];
    if (list.indexOf(size) >= 0) {
      return "ant-button-".concat(size);
    }
    return "ant-button-medium";
  }
  function getHoverClass(loading, type, activeClassName) {
    if (loading) {
      return "";
    }
    var className = "ant-button-active";
    if (type === "text") {
      className += " ant-button-text-active";
    }
    if (activeClassName) {
      className += " " + activeClassName;
    }
    return className;
  }
  function isAide(aide, type) {
    return aide && ["default", "primary"].indexOf(type) > -1;
  }
  var Button_default = {
    getClass,
    getHoverClass,
    isAide
  };

  // node_modules/tslib/tslib.es6.js
  function __spreadArray(to, from, pack) {
    if (pack || arguments.length === 2) for (var i = 0, l = from.length, ar; i < l; i++) {
      if (ar || !(i in from)) {
        if (!ar) ar = Array.prototype.slice.call(from, 0, i);
        ar[i] = from[i];
      }
    }
    return to.concat(ar || Array.prototype.slice.call(from));
  }

  // mini:behavior
  var getValueFromProps = (instance, keys) => Array.isArray(keys) ? keys.map((key) => instance.props[key]) : instance.props[keys];
  var triggerEvent = (instance, name, value, event) => instance.change(value, event);
  var tabsChange = function(e) {
    var index = parseInt(e.currentTarget.dataset.index, 10);
    var items = getValueFromProps(this, "items");
    if (items[index].disabled) {
      return;
    }
    if (this.getValue() === index) {
      return;
    }
    if (!this.isControlled()) {
      this.update(index);
    }
    triggerEvent(this, "change", index, e);
  };
  var collapseChange = function(e) {
    var itemIndex = parseInt(e.currentTarget.dataset.index, 10);
    var _a = getValueFromProps(this, [
      "items",
      "accordion"
    ]), items = _a[0], accordion = _a[1];
    if (items[itemIndex] && items[itemIndex].disabled) {
      return;
    }
    var arr = this.getValue();
    var current = __spreadArray([], arr, true);
    var index = current.indexOf(itemIndex);
    if (index >= 0) {
      current.splice(index, 1);
    } else {
      if (accordion) {
        current = [itemIndex];
      } else {
        current.push(itemIndex);
        current.sort();
      }
    }
    if (!this.isControlled()) {
      this.update(current);
    }
    triggerEvent(this, "change", current, e);
  };

  // web.js
  function button(node) {
    const type = node.dataset.antButton || "default";
    node.classList.add(
      "ant-button",
      "ant-button-inline",
      "ant-button-" + type,
      Button_default.getClass(node.dataset.antSize)
    );
    return node;
  }
  function tabs(list, getValue, change) {
    const nodes = [...list.querySelectorAll('[role="tab"]')];
    const instance = {
      props: { items: nodes.map((node) => ({ disabled: node.disabled })) },
      getValue,
      change,
      isControlled: () => true
    };
    nodes.forEach((node, index) => {
      node.dataset.index = String(index);
      node.addEventListener("click", (event) => tabsChange.call(instance, event));
    });
  }
  function collapse(container) {
    const items = [...container.children].filter((node) => node.tagName === "DETAILS");
    container.classList.add("ant-collapse");
    const instance = {
      props: { items: items.map(() => ({})), accordion: container.dataset.antCollapse === "accordion" },
      isControlled: () => true,
      getValue: () => items.flatMap((item, index) => item.open ? [index] : []),
      change(current) {
        items.forEach((item, index) => {
          item.open = current.includes(index);
        });
      }
    };
    items.forEach((item, index) => {
      const summary = item.querySelector("summary");
      if (!summary) return;
      item.classList.add("ant-collapse-item");
      summary.classList.add("ant-collapse-item-title");
      summary.firstElementChild?.classList.add("ant-collapse-item-title-node");
      summary.querySelector("svg")?.classList.add("ant-collapse-item-title-arrow");
      for (const child of item.children) {
        if (child !== summary) child.classList.add("ant-collapse-item-content");
      }
      summary.dataset.index = String(index);
      summary.addEventListener("click", (event) => {
        event.preventDefault();
        collapseChange.call(instance, event);
      });
    });
  }
  document.querySelectorAll("[data-ant-button]").forEach(button);
  document.querySelectorAll("[data-ant-collapse]").forEach(collapse);
  window.AntMini = Object.freeze({ button, tabs });
})();
