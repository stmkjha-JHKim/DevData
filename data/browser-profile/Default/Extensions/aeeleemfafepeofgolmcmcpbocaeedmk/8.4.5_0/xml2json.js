// Converts XML to JSON
// from: https://coursesweb.net/javascript/convert-xml-json-javascript_s2
export function XMLtoJSON() {
  var me = this;      // stores the object instantce

  // gets the content of an xml file and returns it in 
  me.fromFile = function(xml, rstr) {
    // Cretes a instantce of XMLHttpRequest object
    var xhttp = (window.XMLHttpRequest) ? new XMLHttpRequest() : new ActiveXObject("Microsoft.XMLHTTP");
    // sets and sends the request for calling "xml"
    xhttp.open("GET", xml ,false);
    xhttp.send(null);

    // gets the JSON string
    var json_str = jsontoStr(setJsonObj(xhttp.responseXML));

    // sets and returns the JSON object, if "rstr" undefined (not passed), else, returns JSON string
    return (typeof(rstr) == 'undefined') ? JSON.parse(json_str) : json_str;
  }

  // returns XML DOM from string with xml content
  me.fromStr = function(xml, rstr) {
    // for non IE browsers
    if(window.DOMParser) {
      var getxml = new DOMParser();
      var xmlDoc = getxml.parseFromString(xml,"text/xml");
    }
    else {
      // for Internet Explorer
      var xmlDoc = new ActiveXObject("Microsoft.XMLDOM");
      xmlDoc.async = "false";
    }

    // gets the JSON string
    var json_str = jsontoStr(setJsonObj(xmlDoc));

    // sets and returns the JSON object, if "rstr" undefined (not passed), else, returns JSON string
    return (typeof(rstr) == 'undefined') ? JSON.parse(json_str) : json_str;
  }

  // receives XML DOM object, returns converted JSON object
  var setJsonObj = function(xml) {
    var js_obj = {};
    if (xml.nodeType == 1) {
      if (xml.attributes.length > 0) {
        js_obj["@attributes"] = {};
        for (var j = 0; j < xml.attributes.length; j++) {
          var attribute = xml.attributes.item(j);
          js_obj["@attributes"][attribute.nodeName] = attribute.value;
        }
      }
    } else if (xml.nodeType == 3) {
      js_obj = xml.nodeValue;
    }            
    if (xml.hasChildNodes()) {
      for (var i = 0; i < xml.childNodes.length; i++) {
        var item = xml.childNodes.item(i);
        var nodeName = item.nodeName;
        if (typeof(js_obj[nodeName]) == "undefined") {
          js_obj[nodeName] = setJsonObj(item);
        } else {
          if (typeof(js_obj[nodeName].push) == "undefined") {
            var old = js_obj[nodeName];
            js_obj[nodeName] = [];
            js_obj[nodeName].push(old);
          }
          js_obj[nodeName].push(setJsonObj(item));
        }
      }
    }
    return js_obj;
  }

  // converts JSON object to string (human readablle).
  // Removes '\t\r\n', rows with multiples '""', multiple empty rows, '  "",', and "  ",; replace empty [] with ""
  var jsontoStr = function(js_obj) {
    var rejsn = JSON.stringify(js_obj, undefined, 2).replace(/(\\t|\\r|\\n)/g, '').replace(/"",[\n\t\r\s]+""[,]*/g, '').replace(/(\n[\t\s\r]*\n)/g, '').replace(/[\s\t]{2,}""[,]{0,1}/g, '').replace(/"[\s\t]{1,}"[,]{0,1}/g, '').replace(/\[[\t\s]*\]/g, '""');
    return (rejsn.indexOf('"parsererror": {') == -1) ? rejsn : 'Invalid XML format';
  }
  
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