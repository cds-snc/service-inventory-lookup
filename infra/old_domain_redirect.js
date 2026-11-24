// Redirects the old per-tool domains to their pages on the lookup domain.
var TARGET = "https://lookup.gcorgs.cdssandbox.xyz";

// Host => tool path prefix and the data files that tool served at its root
var TOOLS = {
  "service-inventory-lookup.gcorgs.cdssandbox.xyz": {
    name: "service",
    files: ["service.js", "services.json"],
  },
  "program-code-lookup.gcorgs.cdssandbox.xyz": {
    name: "program",
    files: ["program.js", "program_codes.json"],
  },
};

function queryString(qs) {
  var parts = [];
  for (var name in qs) {
    var values = qs[name].multiValue || [qs[name]];
    for (var i = 0; i < values.length; i++) {
      parts.push(values[i].value === "" ? name : name + "=" + values[i].value);
    }
  }
  return parts.length ? "?" + parts.join("&") : "";
}

function targetPath(tool, uri) {
  if (!tool) return "/";
  if (uri === "/.well-known/security.txt") return uri;
  if (uri === "/fr") return "/" + tool.name + "/fr";
  if (tool.files.indexOf(uri.slice(1)) !== -1) return "/" + tool.name + uri;
  return "/" + tool.name + "/en";
}

function handler(event) {
  var request = event.request;
  var host = request.headers.host ? request.headers.host.value : "";
  var location = TARGET + targetPath(TOOLS[host], request.uri) + queryString(request.querystring);

  return {
    statusCode: 301,
    statusDescription: "Moved Permanently",
    headers: { location: { value: location } },
  };
}
