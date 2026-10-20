// 搬运自 prototype.html:1181-1182。hashchange 的绑定在 main.js（原型的 1183 行）。
  export const routeOf = () => (location.hash.replace(/^#\/?/, "") || "home");
  export const go = (route) => { location.hash = "#/" + route; };
