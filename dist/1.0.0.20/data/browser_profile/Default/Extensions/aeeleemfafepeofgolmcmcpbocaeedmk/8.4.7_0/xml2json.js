// Converts XML to JSON
// from: https://coursesweb.net/javascript/convert-xml-json-javascript_s2
export function XMLtoJSON() {
  var me = this;      // stores the object instantce

  me.XmlToJsonEx = function(xml)  {
  xml = xml.trim();
  const tagPattern = /^<([^\s/>]+)(.*?)>([\s\S]*?)<\/\1>/;
  const selfClosingPattern = /^<([^\s/>]+)(.*?)[\/]>/;

  function parse(xmlStr) {
    const result = {};

    while (xmlStr.length > 0) {
      xmlStr = xmlStr.trim();

      if (xmlStr.startsWith('<!--')) {
        const end = xmlStr.indexOf('-->');
        if (end === -1) break;
        xmlStr = xmlStr.slice(end + 3);
        continue;
      }

      if (xmlStr.startsWith('<![CDATA[')) {
        const end = xmlStr.indexOf(']]>');
        if (end === -1) break;
        return [xmlStr.slice(9, end), xmlStr.slice(end + 3)];
      }

      const tagMatch = xmlStr.match(tagPattern);
      const selfCloseMatch = xmlStr.match(selfClosingPattern);

      if (tagMatch) {
        const [full, tag, attrStr, inner] = tagMatch;
        const attrs = {};
        attrStr.trim().replace(/([^\s=]+)="([^"]*)"/g, (_, k, v) => {
          attrs[k] = v;
        });

        const [childResult] = parse(inner);
        const content = typeof childResult === "object" ? { ...attrs, ...childResult } : (Object.keys(attrs).length ? { ...attrs, value: childResult } : childResult);

        if (!result[tag]) {
          result[tag] = content;
        } else if (Array.isArray(result[tag])) {
          result[tag].push(content);
        } else {
          result[tag] = [result[tag], content];
        }

        xmlStr = xmlStr.slice(full.length);
      } else if (selfCloseMatch) {
        const [full, tag, attrStr] = selfCloseMatch;
        const attrs = {};
        attrStr.trim().replace(/([^\s=]+)="([^"]*)"/g, (_, k, v) => {
          attrs[k] = v;
        });
        const content = Object.keys(attrs).length ? attrs : "";

        if (!result[tag]) {
          result[tag] = content;
        } else if (Array.isArray(result[tag])) {
          result[tag].push(content);
        } else {
          result[tag] = [result[tag], content];
        }

        xmlStr = xmlStr.slice(full.length);
      } else {
        // 텍스트 노드
        const textEnd = xmlStr.indexOf('<');
        const text = textEnd === -1 ? xmlStr : xmlStr.slice(0, textEnd);
        return [text.trim(), xmlStr.slice(text.length)];
      }
    }

    return [result, ''];
  }

  // 루트 제거 처리
  const rootMatch = xml.match(/^<([^\s/>]+)[^>]*>([\s\S]*)<\/\1>$/);
  if (!rootMatch) return {};

  const [, , innerXml] = rootMatch;
  const [parsedResult] = parse(innerXml);
  return parsedResult;
  }
};	