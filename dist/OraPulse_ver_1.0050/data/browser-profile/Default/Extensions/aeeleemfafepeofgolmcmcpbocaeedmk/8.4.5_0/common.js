var g_dns = ['.com', '.net', '.org', '.edu', '.gov', '.biz', '.info', '.tn', '.rs', '.ma', '.sk', '.cz', '.us'];

export function PercentReplacer(match) {
	if (match.length < 3 || match.match(/[^a-fA-F0-9]/g).length > 1)
	{
		return match.replaceAll("%","%25");
	}
	return match;
}

export function getHostFromURL(url)
{
	var hostname = "";
	var domain = "";
	var suburl = "";
	var TwoStepDNS = false;

	var p = url.indexOf("//");
	if(p < 0) return {hostname:""};

	url = url.substring(p+2);
	p = url.indexOf("/");
	if(p > -1)
	{
		suburl = url.substring(p);
		url = url.substring(0, p);
	}
	p = url.indexOf("www.");
	if (p > -1) url = url.substring(p+4);
	hostname = url;

	// 2단계
	p = url.lastIndexOf(".");
	if (p > 0)
	{
		var word = url.substring(p);
		for (var prop in g_dns)
		{
			if (word.indexOf(g_dns[prop]) > -1)
			{
				//console.log("[getHostFromURL] TwoStepDNS");
				TwoStepDNS = true;
				break;
			}
		}
	}
	// 3단계
	var dotcount = 0;
	var url_len = url.length;
	for (var index = 0; index < url_len; index++)
	{
		if (url[index] == ".") dotcount++;
	}

	//console.log("[getHostFromURL] dotcount - " + dotcount);

	if (dotcount > 1)
	{
		var nCnt = 3;
		if (TwoStepDNS)
			nCnt--;

		if (dotcount >= nCnt)
		{
			var position = url.indexOf(".");
			domain = url.substring(position+1);
			//console.log("[getHostFromURL] ## 1 ## domain - " + domain);
			if (dotcount > nCnt)
			{
				position = domain.indexOf(".");
				domain = domain.substring(position+1);
				//console.log("[getHostFromURL] ## 2 ## domain - " + domain);
			}
		}
	}

	if (suburl != "")
	{
		p = suburl.indexOf("?");
		if (p > -1)
		{
			suburl = suburl.substring(0, p);
		}

		while (suburl.indexOf("//") > -1)
		{
			suburl = suburl.replace("//", "/");
		}

		p = suburl.lastIndexOf("/");
		if (p == suburl.length - 1)
		{
			suburl = suburl.substring(0, p);
		}
	}

	return {hostname:"" + hostname + "", domain:"" + domain + "", suburl:"" + suburl + ""};
}

export function GetPacketData(details)
{
	var packetData;
	if (details.requestBody.formData)
	{
		console.log("[GetPacketData] form data");
		packetData = details.requestBody.formData;
	}
	else
	{
		console.log("[GetPacketData] raw data");
		if (details.requestBody.raw == undefined)
		{
			return "requestBodyUndefined";
		}
		var utfString8 = new stringview.StringView(details.requestBody.raw[0].bytes);
		//var BMIString = /\<DATA\>\<DLMAIL\>\<\/DLMAIL\>/g;		//웹메일의 패킷은 이런형식으로 처음에 시작하는 부분이 있다. DLMAIL이라는 부분에 값이 생성될수도 있으니까 <DATA><DLMAIL><까지 입력한 경우 해당 패킷으로 인식해도 될듯하다
		var HTMLString = /\<DATA\>/g;

		//console.log("[GetPacketData] url : " + details.url);
		//console.log("[GetPacketData] utfString8 : " + utfString8);

		var CDATAPattern = /%3C!%5BCDATA%5B/g;
		if (CDATAPattern.test(utfString8) == true)
		{
			//if (details.url.indexOf("autowaymail") >= 0) // 그룹웨어 지원을 위해 추가된 조건였으나, 다른 그룹웨어에서도 동일하여 일반화하여 적용
			//{
				var data = utfString8.toString().replace(/'/g, "\"");
				data = data.replace("pStrXMLMailItemInfo", "\"pStrXMLMailItemInfo\"");
				data = data.replace("pStrOption", "\"pStrOption\"");
				data = data.replace("pStrBigAttachXML", "\"pStrBigAttachXML\"");
				//console.log(data);
				var jsonData = JSON.parse(data);
				packetData = parseCDATA(jsonData.pStrXMLMailItemInfo);
				return packetData;
			//}
		}
		else if (HTMLString.test(utfString8) == true)
		{
			utfString8 = parseCDATA(utfString8.toString());
			console.log("utfString8 : " + utfString8);

			return utfString8;
		}

		// JSON Data
		packetData = GetJSONData(utfString8.toString());
		var dwrPattern = /\bdwr\b/g;
		if (dwrPattern.test(details.url))
		{
			packetData = getdwrVars(utfString8.toString()); // 다음 댓글
		}
		else if (typeof(packetData) == "string") // exception 발생
		{
			packetData = getUrlVars(utfString8.toString()); //몇몇 사이트에서 특수문자를 기입할 경우 formdata가 오지 않고 인코딩되서 옴
		}
	}

	return packetData;
}

export function parseCDATA(data)
{
	//Decoding을 3번 진행한다.
	var myJson = {};
	var decodedata = "";
	for (var nCnt = 0; nCnt < 3; nCnt++)
	{
		data = data.replace(/%.{0,2}/g, PercentReplacer);
		decodedata = decodeURIComponent(data.replace(/\+/g, " "));
		data = decodedata;
	}

	console.log(data);

	var xmltojson = new xml2json.XMLtoJSON();
	myJson = xmltojson.XmlToJsonEx(data);
	
	console.log(myJson);
	return myJson;
}

export function GetKeywordObj(KeywordSettings, ExceptionKeywordSettings, analysisData)
{
	var tab = "\t";
	var KeywordTotal = 0;
	var KeywordResult = "";

	if (KeywordSettings != null)
	{
		var KeywordSettingsLength = KeywordSettings.length; //반복해서 갯수를 구해오지 않기 위함
		for (var KeywordIndex = 0; KeywordIndex < KeywordSettingsLength; KeywordIndex++)
		{
			var KeywordCnt = 0;
			var position = "";
			var KeywordReg = new RegExp(KeywordSettings[KeywordIndex].pattern, "g");
			console.log("[GetKeywordObj] keyword Name - " + KeywordSettings[KeywordIndex].name + " pattern - " + KeywordReg + " type - " + KeywordSettings[KeywordIndex].type);
			if (KeywordReg.test(analysisData) == true)
			{
				KeywordReg.lastIndex = 0;
				var indexOfdata;
				while (indexOfdata = KeywordReg.exec(analysisData))
				{
					if (keyword.IsKeywordPattern(indexOfdata, KeywordSettings[KeywordIndex].type) == true)
					{
						if (ExceptionKeywordSettings != null && keyword.IsExceptKeywordPattern(indexOfdata[0], ExceptionKeywordSettings[KeywordSettings[KeywordIndex].type]))
						{
							continue;
						}
						KeywordCnt++;
						//console.log("[GetKeywordObj] indexOfdata = " + indexOfdata + " position = " + (KeywordReg.lastIndex - indexOfdata[0].length));
						position += ((KeywordReg.lastIndex - indexOfdata[0].length) + ".");
					}
				}

				if (KeywordCnt > 0)
				{
					KeywordTotal += KeywordCnt;
					KeywordResult += (KeywordSettings[KeywordIndex].name + tab + KeywordCnt + tab+ KeywordSettings[KeywordIndex].pattern + tab + position + "~");
				}

				console.log("[GetKeywordObj] KeywordCnt : " + KeywordCnt + " position : " + position);
			}
		}	
	}

	return {"KeywordTotal" : KeywordTotal, "KeywordResult" : KeywordResult};
}

export function GetReaction (Action, url, KeywordTotal)
{
	var bLog = false;
	var bSaveCopy = false;
	var bWarn = false;
	var bBlock = false;

	if (Action.BLOCK)
	{
		if (CheckCategory(Action.BLOCK.categorylist, Action.BLOCK.OP, url) == true)
		{
			if (KeywordTotal >= Action.BLOCK.keywordcnt)
			{
				bBlock = true;
			}
		}	
	}

	if (bBlock == false)
	{
		if (Action.LOG)
		{
			if (CheckCategory(Action.LOG.categorylist, Action.LOG.OP, url) == true)
			{
				if (KeywordTotal >= Action.LOG.keywordcnt)
				{
					bLog = true;
					if (Action.SAVECOPY)
					{
						if (CheckCategory(Action.SAVECOPY.categorylist, Action.SAVECOPY.OP, url) == true)
						{
							bSaveCopy = true;
						}
					}
				}
			}
		}

		if (Action.WARN)
		{
			if (CheckCategory(Action.WARN.categorylist, Action.WARN.OP, url) == true)
			{
				if (KeywordTotal >= Action.WARN.keywordcnt)
				{
					bWarn = true;
				}
			}
		}
	}

	

	return {"bLog" : bLog, "bSaveCopy" : bSaveCopy, "bWarn" : bWarn, "bBlock" : bBlock};
}

export function GetGWReaction(Action, KeywordTotal)
{
	var bLog = false;
	var bSaveCopy = false;
	var bWarn = false;
	var bBlock = false;

	if (Action.BLOCK)
	{
		if (KeywordTotal >= Action.BLOCK.keywordcnt)
		{
			bBlock = true;
		}
	}

	if (bBlock == false)
	{
		if (Action.LOG)
		{
			if (KeywordTotal >= Action.LOG.keywordcnt)
			{
				bLog = true;
				bSaveCopy = true;
			}
		}
	}

	if (Action.WARN)
	{
		if (KeywordTotal >= Action.WARN.keywordcnt)
		{
			bWarn = true;
		}
	}

	return {"bLog" : bLog, "bSaveCopy" : bSaveCopy, "bWarn" : bWarn, "bBlock" : bBlock};
}

export function CheckCategory (categorylist, OP, detailurl)
{
	var check = true;

	if (OP == 2)
	{
		return check;
	}

	var url = getHostFromURL(detailurl);
	url.hostname = url.hostname.toLowerCase();
	var categoryMatch = categorylist.some(x => ((x.indexOf("*") == 0) ? detailurl.indexOf(x.substring(1)) >= 0 : ((x === url.hostname) || (x === url.domain) || (x ===(url.hostname+url.suburl)))));

	console.log("[CheckCategory] categorylist : " + categorylist + " url : " + url + " url.hostname : " + url.hostname);
	console.log("[CheckCategory] OP : " + OP + " Match : " + categoryMatch);
	if (OP == 1 && categoryMatch == false) //OP == 1 (EQ)
	{
		check = false;
	}
	else if (OP == 0 && categoryMatch == true) //OP == 0 (NE)
	{
		check = false;
	}

	return check;
}

export function GetWebMailBodyData(object, url)
{
	console.log("{object} url - " + url);
	console.log(object)
	//console.log(JSON.stringify(object));

	var retObj;
	var from;
	var to;
	var cc;
	var bcc;
	var subject;
	var bodyData;

	/**********************MailInfo**********************/
	if (PolicyObj.MailInfo)
	{
		//console.log("[GetWebMailBodyData] PolicyObj.MailInfo");
		var MailInfoCnt = PolicyObj.MailInfo.length;
		for (var nCnt = 0; nCnt < MailInfoCnt; nCnt++)
		{
			if (url.indexOf(PolicyObj.MailInfo[nCnt].host) > -1)
			{
				var rootObject;
				var root = ParseObject(object, PolicyObj.MailInfo[nCnt].root, false, ";");
				if (PolicyObj.MailInfo[nCnt].xml != undefined && PolicyObj.MailInfo[nCnt].xml == "true")
				{
					var xmldata = root;
					if (typeof(GetJSONData(xmldata)) == "string")
					{
						var xmltojson = new xml2json.XMLtoJSON();
						root = xmltojson.XmlToJsonEx(xmldata);
						
						port_.postMessage({"text":"#PostDataXmlToJson#", "postData" : root});
					}
				}

				if (!root)
				{
					continue;
				}

				//console.log("{root}" + nCnt);
				//console.log(root);
				if (typeof(root) == "string")
				{
					rootObject = GetJSONData(root);
				}
				else if (typeof(root) == "object")
				{
					rootObject = root;
				}

				var bAnalysis = true;
				if (PolicyObj.MailInfo[nCnt].sendmailkey)
				{
					bAnalysis = false;
					var sendmailkey = ParseObject(rootObject, PolicyObj.MailInfo[nCnt].sendmailkey, false, ";");
					console.log("sendmailkey : " + sendmailkey);
					
					if (sendmailkey)
					{
						for (var prop in PolicyObj.MailInfo[nCnt].sendmailvalue)
						{
							if (sendmailkey.indexOf(PolicyObj.MailInfo[nCnt].sendmailvalue[prop]) > -1)
							{
								bAnalysis = true;
								break;
							}
						}
					}
				}

				if (bAnalysis)
				{
					from = ParseObject(rootObject, PolicyObj.MailInfo[nCnt].from, true, ";");
					to = ParseObject(rootObject, PolicyObj.MailInfo[nCnt].to, true, ";");
					cc = ParseObject(rootObject, PolicyObj.MailInfo[nCnt].cc, true, ";");
					bcc = ParseObject(rootObject, PolicyObj.MailInfo[nCnt].bcc, true, ";");
					subject = ParseObject(rootObject, PolicyObj.MailInfo[nCnt].subject, true, ";");
					bodyData = ParseObject(rootObject, PolicyObj.MailInfo[nCnt].body, true, ";");

					if (bodyData)
					{
						console.log("[GetWebMailBodyData] body 확인 - " + bodyData);
						if (PolicyObj.MailInfo[nCnt].hasOwnProperty("body_base64"))
						{
							if (PolicyObj.MailInfo[nCnt].body_base64 == true)
							{
								bodyData = Base64Decoding(bodyData);
							}
						}
						break;
					}
				}
			}
		}	
	}

	retObj = {"from" : from, "to" : to, "cc" : cc, "bcc" : bcc, "subject" : subject, "bodyData" : bodyData};
	console.log("{MailData}");
	console.log(retObj);

	return retObj;
}

export function GetWebInputBodyData(object, url)
{
	console.log("{object} url - " + url);
	console.log(object)

	var ret = "";
	var author;
	var contents;
	var subject;
	var comments;

	/**********************WebInputInfo**********************/
	if (PolicyObj.WebInputInfo)
	{
		//console.log("[GetWebInputBodyData] PolicyObj.WebInputInfo");
		var WebInputInfoCnt = PolicyObj.WebInputInfo.length;
		for (var nCnt = 0; nCnt < WebInputInfoCnt; nCnt++)
		{
			if (url.indexOf(PolicyObj.WebInputInfo[nCnt].host) > -1)
			{
				var rootObject;
				var root = ParseObject(object, PolicyObj.WebInputInfo[nCnt].root, false, "\n");
				if (PolicyObj.WebInputInfo[nCnt].xml != undefined && PolicyObj.WebInputInfo[nCnt].xml == "true")
				{
					var xmldata = root;
					if (typeof(GetJSONData(xmldata)) == "string")
					{
						var xmltojson = new xml2json.XMLtoJSON();
						root = xmltojson.XmlToJsonEx(xmldata);
						
						port_.postMessage({"text":"#PostDataXmlToJson#", "postData" : root});
					}
				}

				//console.log("{root}" + nCnt);
				//console.log(root);
				if (typeof(root) == "string")
				{
					rootObject = GetJSONData(root);
				}
				else if (typeof(root) == "object")
				{
					rootObject = root;
				}

				var bAnalysis = true;
				if (PolicyObj.WebInputInfo[nCnt].sendwebinputkey)
				{
					bAnalysis = false;
					var sendwebinputkey = ParseObject(rootObject, PolicyObj.WebInputInfo[nCnt].sendwebinputkey, false, "\n");
					console.log("sendwebinputkey("+ typeof(sendwebinputkey) + ") : " + sendwebinputkey);

					if (typeof(sendwebinputkey) == "string")
					{
						for (var prop in PolicyObj.WebInputInfo[nCnt].sendwebinputvalue)
						{
							if (sendwebinputkey.indexOf(PolicyObj.WebInputInfo[nCnt].sendwebinputvalue[prop]) > -1)
							{
								bAnalysis = true;
								break;
							}	
						}
					}
					else if (typeof(sendwebinputkey) == "boolean")
					{
						if (sendwebinputkey == PolicyObj.WebInputInfo[nCnt].sendwebinputvalue)
						{
							console.log("match!!");
							bAnalysis = true;
						}
					}
				}

				if (bAnalysis)
				{
					if (PolicyObj.WebInputInfo[nCnt].hasOwnProperty("author"))
					{
						author = ParseObject(rootObject, PolicyObj.WebInputInfo[nCnt].author, true, "\n");
						console.log("author : " + author);
					}
					if (PolicyObj.WebInputInfo[nCnt].hasOwnProperty("subject"))
					{
						subject = ParseObject(rootObject, PolicyObj.WebInputInfo[nCnt].subject, true, "\n");
						console.log("subject : " + subject);
					}
					if (PolicyObj.WebInputInfo[nCnt].hasOwnProperty("contents"))
					{
						contents = ParseObject(rootObject, PolicyObj.WebInputInfo[nCnt].contents, true, "\n");
						console.log("contents : " + contents);
					}
					
					if (PolicyObj.WebInputInfo[nCnt].hasOwnProperty("comments"))
					{
						comments = ParseObject(rootObject, PolicyObj.WebInputInfo[nCnt].comments, true, "\n");
						console.log("comments : " + comments);
					}
				}

				if (!!contents || !!comments)
				{
					break;
				}
				
			}
		}	
	}

	if (!!contents || !!comments || !!subject)
	{
		console.log("{WebInputData}");
		if (author)
		{
			ret += ("##########\ninput\n" + "author" + "\n" + "6" + "\n"+ author + "\n");
		}

		if (subject)
		{
			ret += ("##########\ninput\n" + "subject" + "\n" + "7" + "\n"+ subject + "\n");
		}

		if (contents)
		{
			ret += ("##########\ninput\n" + "contents" + "\n" + "8" + "\n"+ contents + "\n");
		}

		if (comments)
		{
			ret += ("##########\ninput\n" + "comments" + "\n" + "8" + "\n"+ comments + "\n");
		}
		
		console.log(ret);
	}

	return ret;
}

export function GetWebInputBodyDataXmlhttprequest(url)
{
	var ret = "";
	var contents;

	/**********************WebInputInfo**********************/
	if (PolicyObj.WebInputInfo)
	{
		//console.log("[GetWebInputBodyDataXmlhttprequest] PolicyObj.WebInputInfo");
		var WebInputInfoCnt = PolicyObj.WebInputInfo.length;
		for (var nCnt = 0; nCnt < WebInputInfoCnt; nCnt++)
		{
			if (PolicyObj.WebInputInfo[nCnt].xmlhttprequest != undefined && PolicyObj.WebInputInfo[nCnt].xmlhttprequest == "true")
			{
				if (url.indexOf(PolicyObj.WebInputInfo[nCnt].host) > -1)
				{
					const urlObj = new URL(url);
					const params = urlObj.searchParams;
					
					if (PolicyObj.WebInputInfo[nCnt].pcontents != undefined)
					{
						contents = params.get(PolicyObj.WebInputInfo[nCnt].pcontents);
					}
					if (!!contents)
						break;
					else
						continue;
				}
			}
		}	
	}

	if (!!contents)
	{
		if (contents)
		{
			ret = ("##########\ninput\n" + "contents" + "\n" + "8" + "\n"+ contents + "\n");
		}
		
		console.log(ret);
	}

	return ret;
}

export function ParseObject(object, SubList, bDecoding, separator)
{
	var key = object;
	var length = SubList.length;
	for(var prop = 0; prop < length; prop++)
	{  
		if (key == undefined)
		{
			key = "";
			break;
		}
		var Sub = SubList[prop];
		if (Sub == "%" || Sub == "try" || Sub == "find")
		{
			//console.log("[ParseObject] % 시작");
			var ret = "";
			var tmpkey;
			for(var index = 0;;index++)
			{
				tmpkey = GetJSONData(key)[index];
				//console.log(tmpkey);
				if (tmpkey == undefined)
				{
					if (typeof(tmpkey) == "object") 
					{
						continue;
					}
					else
					{
						//console.log("tmpkey undefined");
						break; //for(var index = 0;;index++)
					}
				}

				if (typeof(tmpkey) == "string")
				{
					//console.log("[ParseObject] tmpkey : " + tmpkey);
					ret += tmpkey;
					ret += separator;
				}
				else
				{
					var Sub2 = SubList[prop+1];
					//console.log("[ParseObject] Sub2 : " + Sub2);
					console.log(tmpkey[Sub2]);
					if (typeof(Sub2) == "object")
					{
						var fineValue = ParseObject(tmpkey, Sub2.slice(1, Sub2.length), bDecoding, "");
						if (fineValue == Sub2[0])
						{
							ret += ParseObject(tmpkey, SubList.slice(prop+2, length), bDecoding, "");
							ret += separator;
						}
					}
					else if (typeof(tmpkey[Sub2]) == "object")
					{
						if (Sub == "find")
						{
							ret = ParseObject(tmpkey[Sub2], SubList.slice(prop+2, length), bDecoding, "");
							if (ret != "" && typeof(ret) == "object")
								break;
						}
						else
						{
							ret += ParseObject(tmpkey[Sub2], SubList.slice(prop+2, length), bDecoding, "");
							ret += separator;
						}
					}
					else
					{
						ret += tmpkey[Sub2];
						ret += separator;
					}
				}
			}
			
			if (Sub == "try")
			{
				if (ret != "")
				{
					key = ret;
					prop++;
				}
				continue;
			}
			key = ret;
			break; //for(var prop in SubList)
		}
		else if (Sub == "[]")
		{
			console.log("[ParseObject] [] 시작");
			key = key.replace(/\\\"/g, "");
			key = "[" + key + "]";
			//console.log(key);
		}
		else
		{
			if (typeof(key) == "string")
			{
				key = GetJSONData(key);
				if (typeof(key) == "object")
				{
					key = key[Sub];
				}
			}
			else
			{
				key = key[Sub];
			}
		}
	}

	if (bDecoding)
	{
		var URIEncdoingPattern = /%[\d|a-zA-Z][\d|a-zA-Z]/g;
		if (URIEncdoingPattern.test(key) == true)
		{
			//console.log(key);
			try
			{
				key = key.replace(/%.{0,2}/g, PercentReplacer);
				key = decodeURIComponent(key.replace(/\+/g, " "));
			}
			catch
			{
				//console.log("catch!!! key - " + key);
			}
			
		}
	}

	return key;
}

export function getdwrVars(url) {
	var hash;
    var myJson = {};
    var hashes = url.split('\n');
    for (var i = 0; i < hashes.length-1; i++) {
		hash = hashes[i].split('=');
		//console.log("hash : " + hash);
		if (hash.length < 2)
		{
			continue;
		}
		hash[1] = hash[1].replace(/%.{0,2}/g, PercentReplacer);
		var value = decodeURIComponent(hash[1].replace(/\+/g, " ")).replace(/\D+\:/g, "");
		//console.log("value : " + value);
        myJson[hash[0]] = value;
    }
    return myJson;
}

export function getUrlVars(url) {
    var hash;
    var myJson = {};
    var hashes = url.split('&');
    for (var i = 0; i < hashes.length; i++) {
		hash = hashes[i].split('=');
		//console.log("hash : " + hash);
		if (hash.length < 2)
		{
			continue;
		}
		
		hash[1] = hash[1].replace(/%.{0,2}/g, PercentReplacer);
		var value = decodeURIComponent(hash[1].replace(/\+/g, " "));
		//console.log("value : " + value);
        myJson[hash[0]] = value;
    }
    return myJson;
}

export function getWebInputData(postDataObj, checkValueMatch) {
	var sContents = "";
	var keyArray = Object.keys(postDataObj);

	if (keyArray[0] == null)
	{
		console.log("filters ...");
		return sContents;
	}

	var bContents = false;
	for (var nIndex=0; nIndex < keyArray.length; nIndex++)
	{
		var Value = "";
		var temp = postDataObj[keyArray[nIndex]];
		if (typeof temp == 'object')
		{
			Value = JSON.stringify(temp);
		}
		else
		{
			Value = temp + "";
		}

		if (IsPostValueFilter(keyArray[nIndex], Value, checkValueMatch) == false)
		{
			sContents += ("##########\ninput\n" + keyArray[nIndex] + "\n" +keyArray[nIndex].length + "\n"+ Value + "\n");
			if (Value.length > PolicyObj.WEBINPUT.webinputlimit)
			{
				bContents = true;
			}
		}
	}

	if (bContents == false)
	{
		sContents = "";
	}

	return sContents;
}

export function IsPostValueFilter(key, Value, checkValueMatch)
{
	key = key.toLowerCase();
	if (key.indexOf("content") > -1) return false;
	if (key.indexOf("subj") > -1) return false;
	if (key.indexOf("title") > -1) return false;
	if (key.indexOf("from") > -1) return false;
	if (key.indexOf("to") > -1) return false;
	if (key.indexOf("userid") > -1) return false;
	if (key.indexOf("username") > -1) return false;
	if (key.indexOf("userdept") > -1) return false;
	if (key.indexOf("sender_info") > -1) return false;
	if (key.indexOf("sender_name") > -1)	return false;
	if (key.indexOf("radsendername") > -1) return false;
	if (key.indexOf("bcc") > -1) return false;
	if (key.indexOf("cc") > -1) return false;
	if (key.indexOf("mailbody") > -1) return false;
	if (key.match(/&body/i)) return false;
	if (key.indexOf("&") == -1 && key.indexOf("body") > -1) return false;
	if (key.indexOf("v") == 1 && key.length < 3)	return false;
	if (key.match(/&hidfileinfo/i) && key.match(/&ntag_filename/i) && (key.indexOf("file") > -1 || key.indexOf("&targetpath")>-1 || key == "uploadinfo")) 
	{
		return false;
	}
	if (key.indexOf("&abstract") == 0)	return false;
	if (key.indexOf("fld11") > -1)		return false;
	if (key.indexOf("username") > -1)	return false;
	if (key.indexOf("msgtxt") > -1)		return false;
	if (key.indexOf("m_sender") > -1)	return false;
	if (key.indexOf("msg")==0)			return false;
	if (key.indexOf("maintext")==0)		return false;
	if (key.indexOf("bundles") > -1)	return false;


	if (Value.length < 20) return true;
	if (checkValueMatch && (Value.match(/true/i) || Value.match(/false/i))) return true;

	if (key.indexOf("font") > -1)		return true;
	if (key.indexOf("widgetcode") > -1)	return true;
	if (key.indexOf("color") > -1)		return true;
	if (key.indexOf("attach") > -1)		return true;	
	if (key.indexOf("param") > -1)		return true;
	if (key.indexOf("referer") > -1)		return true;
	if (key.indexOf("degree") > -1)		return true;
	if (key.indexOf("type")> -1)		return true;
	if (key.indexOf("log") > -1)			return true;
	if (key.indexOf("url") > -1)			return true;
	if (key.indexOf("session") > -1)		return true;
	if (key.indexOf("domain") > -1)		return true;
	if (key.indexOf("enc") > -1)			return true;
	if (key.indexOf("cert") > -1)		return true;
	if (key.indexOf("key") > -1)			return true;
	if (key.indexOf("temp") > -1)		return true;
	if (key.indexOf("plug") > -1)		return true;
	if (key.indexOf("avata") > -1)		return true;
	if (key.indexOf("skin") > -1)		return true;
	if (key.indexOf("media") > -1)		return true;
	if (key.indexOf("tick") > -1)		return true;
	if (key.indexOf("list") > -1)		return true;
	if (key.indexOf("butt") > -1)		return true;
	if (key.indexOf("event") > -1)		return true;
	if (key.indexOf("view") > -1)		return true;
	if (key.indexOf("dummy") > -1)		return true;
	if (key.indexOf("alert") > -1)		return true;
	if (key.indexOf("qv") == 1)			return true;
	if (key.indexOf("str") == 1)			return true;	
	if (key.indexOf("postdata") == 1)	return true;
	if (key.indexOf("token") > -1)		return true;
	if (key.indexOf("to_view") > -1)		return true;	
	if (key.indexOf("callcount") > -1)	return true;
	if (key.indexOf("version") > -1)		return true;
	if (key.indexOf("issacweb_data") > -1)		return true;
	if (key.indexOf("bmterm_") > -1)				return true;
	if (key.indexOf("__previous") > -1)			return true;
	if (key.indexOf("vcont") == 1)				return true;
	if (key.indexOf("__requestdigest") > -1)		return true;
	if (key.indexOf("scriptmanager") > -1)		return true;
	if (key.indexOf("instanceid") > -1)			return true;
	if (key.indexOf("href") == 1)				return true;
	if (key.indexOf("_selectednode") > -1)		return true;
	if (key.indexOf("guid") > -1)				return true;
	if (key.indexOf("bottom") > -1)				return true;
	if (key.indexOf("tool") > -1)				return true;
	if (key.indexOf("cookie") > -1)				return true;
	if (key.indexOf("&ir1") > -1)		return true;
	if (key.indexOf("&mimebody") == 0)		return true;
	if (key.indexOf("%24_items") > 0)		return true;
	if (key.indexOf("&") > -1 && key.length < 3) return true;
	if (key.match(/ms/i))		return true;
	if (key.indexOf("&sigbody") > -1)	return true;
	if (key.indexOf("ir1")==0)	return true;
	if (key.match(/&ntag_filename/i))	return true;

	return false;
}

export function GetJSONData(str)
{
	try
	{
		console.log(str);
		var json = JSON.parse(str);
		return json;
	}
	catch (e)
	{
		console.log("Not JSON Data");
		console.log(e.message);
		return str;
	}
}

export function IsCheckValueMatch(details)
{
	var ret = true;

	if (details.initiator != undefined && details.initiator.indexOf("https://cafe.naver.com") > -1)	ret = false;
	if (details.initiator != undefined && details.initiator.indexOf("https://blog.naver.com") > -1)	ret = false;
	if (details.initiator != undefined && details.initiator.indexOf("https://www.facebook.com") > -1) ret = false;

	return ret;
}

export function OnlyNumFilterNGetCharPos(TelNumObject)
{
	var regex = /\D/g;
	TelNumObject.charindex = TelNumObject.data.search(regex);
	
	var regex2 = /[^0-9]/g;
	var result = TelNumObject.data.replace(regex2, "");
	TelNumObject.data = result;
	
	TelNumObject.datalen = TelNumObject.data.length
}

export function Base64Decoding(bodyData)
{
	var ret = bodyData;
	if (bodyData.indexOf("Content-Transfer-Encoding: base64") > -1)
	{
		var findstring = "Content-Type: text/html;";
		var FindPos = bodyData.indexOf(findstring);
		if (FindPos > -1)
		{
			var SPos = bodyData.indexOf("\n\n", FindPos);
			if (SPos > -1)
			{
				var EPos = bodyData.indexOf("\n\n", SPos+2);
				if (EPos > -1)
				{
					console.log("[Base64Decoding] SPos : " + (SPos+2) + " EPos : " + EPos);
					var BASE64Data = bodyData.slice(SPos+2, EPos);
					ret = stringview.StringView.makeFromBase64(BASE64Data).toString();
				}
			}
		}
	}

	return ret;
}

export function IsPassHost(url)
{
	var ret = false;
	url = url.toLowerCase();
	if (PolicyObj.PasshostList)
	{
		ret = PolicyObj.PasshostList.some(x => (url.indexOf(x) >= 0));
	}

	return ret;
}

export function GetKeywordResultObj(KeywordSettings, keyworditemlist, ExceptionKeywordSettings, analysisData)
{
	// KeywordSettings : id, name, pattern, skipcount, type
	// keyworditemlist : id array

	var tab = "\t";
	var KeywordResultObj = {};

	if (KeywordSettings != null && keyworditemlist != null)
	{
		var KeywordSettingsLength = KeywordSettings.length; //반복해서 갯수를 구해오지 않기 위함
		for (var KeywordIndex = 0; KeywordIndex < KeywordSettingsLength; KeywordIndex++)
		{
			if (keyworditemlist.indexOf(KeywordSettings[KeywordIndex].id) === -1)
			{
				continue;
			}
			
			var KeywordCnt = 0;
			var position = "";
			var KeywordReg = new RegExp(KeywordSettings[KeywordIndex].pattern, "g");
			console.log("[GetKeywordResultObj] Keyword ID - " + KeywordSettings[KeywordIndex].id + " keyword Name - " + KeywordSettings[KeywordIndex].name + " pattern - " + KeywordReg + " type - " + KeywordSettings[KeywordIndex].type);
			if (KeywordReg.test(analysisData) == true)
			{
				KeywordReg.lastIndex = 0;
				var indexOfdata;
				while (indexOfdata = KeywordReg.exec(analysisData))
				{
					if (keyword.IsKeywordPattern(indexOfdata, KeywordSettings[KeywordIndex].type) == true)
					{
						if (ExceptionKeywordSettings != null && keyword.IsExceptKeywordPattern(indexOfdata[0], ExceptionKeywordSettings[KeywordSettings[KeywordIndex].type]))
						{
							continue;
						}
						KeywordCnt++;
						position += ((KeywordReg.lastIndex - indexOfdata[0].length) + ".");
					}
				}

				if (KeywordCnt > 0)
				{
					KeywordResultObj[KeywordSettings[KeywordIndex].id] = {"count": Number(KeywordCnt) || 0, "result" : (KeywordSettings[KeywordIndex].name + tab + Number(KeywordCnt) + tab+ KeywordSettings[KeywordIndex].pattern + tab + position + "~")};
					console.log("[GetKeywordResultObj] position : " + position);
				}
			}
		}	
	}

	// return KeywordResultObj
	// {"id" : {"count" : KeywordCnt, "result" : name \t KeywordCnt \t pattern \t position }, ...}
	// {"39":{"count":5,"result":"휴대전화 A\t5\t01\\d\\D\\d{3}\\D\\d{4}\t110.123.136.149.162.~"},"40":{"count":5,"result":"휴대전화 B\t5\t01\\d\\D\\d{4}\\D\\d{4}\t28.42.56.70.84.~"}}

	return KeywordResultObj;
}

export function GetReactionResultObj(Action, url, keywordResultObj)
{
	var LogObj = {"bAllow" : true};
	var SaveCopyObj = {"bAllow" : true};
	var WarnObj = {"bAllow" : true};
	var BlockObj = {"bAllow" : true};

	if (Action.BLOCK && CheckCategory(Action.BLOCK.categorylist, Action.BLOCK.OP, url) == true)
	{
		BlockObj = CheckKeyword(Action.BLOCK.keywordcnt, Action.BLOCK.keywordscope, Action.BLOCK.keywordcatlist, keywordResultObj);
	}

	if (BlockObj.bAllow == true)
	{
		if (Action.LOG && CheckCategory(Action.LOG.categorylist, Action.LOG.OP, url) == true)
		{	
			LogObj = CheckKeyword(Action.LOG.keywordcnt, Action.LOG.keywordscope, Action.LOG.keywordcatlist, keywordResultObj);
			if (LogObj.bAllow == false)
			{
				if (Action.SAVECOPY && CheckCategory(Action.SAVECOPY.categorylist, Action.SAVECOPY.OP, url) == true)
				{
					SaveCopyObj.bAllow = false;
				}
			}
		}

		if (Action.WARN && CheckCategory(Action.WARN.categorylist, Action.WARN.OP, url) == true)
		{
			WarnObj = CheckKeyword(Action.WARN.keywordcnt, Action.WARN.keywordscope, Action.WARN.keywordcatlist, keywordResultObj);
		}
	}	

	var RetObj = {"block" : BlockObj.bAllow == false, "Log" : LogObj.bAllow == false, "SaveCopy" : SaveCopyObj.bAllow == false, "Warn" : WarnObj.bAllow == false};
	if (BlockObj.bAllow == false)
	{
		RetObj["keywordResult"] = BlockObj.KeywordResult;
		RetObj["keywordTotal"] = BlockObj.KeywordTotal;
	}
	else if (LogObj.bAllow == false)
	{
		RetObj["keywordResult"] = LogObj.KeywordResult;
		RetObj["keywordTotal"] = LogObj.KeywordTotal;
	}
	else
	{
		RetObj["keywordResult"] = "";
		RetObj["keywordTotal"] = 0;
	}
		
	if (WarnObj.bAllow == false)
	{
		RetObj["keywordResultWarn"] = WarnObj.KeywordResult;
		RetObj["keywordTotalWarn"] = WarnObj.KeywordTotal;
	}

	return RetObj;
}

export function CheckKeyword (keywordcnt, keywordscope, keywordcatlist, keywordResultObj)
{
	console.log("[CheckKeyword] keywordcnt : " + keywordcnt + " keywordscope : " + keywordscope + " keywordcatlist : %o", keywordcatlist);

	if (keywordcatlist == null || keywordcatlist.length == 0)
	{
		if (!keywordcnt || Number(keywordcnt) <= 0)
		{
			return {"bAllow" : false, "KeywordTotal" : 0, "KeywordResult" : ""};
		}
		return {"bAllow" : true, "KeywordTotal" : 0, "KeywordResult" : ""};
	}
	else
	{
		var bCatAllow = true, bTotalAllow = true, bAllow = true;

		var TotalCnt = 0;
		var TotalResult = "";
		var keywordcatlistLength = keywordcatlist.length; //반복해서 갯수를 구해오지 않기 위함
		for (var kwIndex = 0; kwIndex < keywordcatlistLength; kwIndex++)
		{
			var CatTotalCnt = 0;
			var Catlimit = keywordcatlist[kwIndex].limit;
			var itemlist = keywordcatlist[kwIndex].itemlist;

			var itemlistLength = itemlist.length;
			for (var itemIndex = 0; itemIndex < itemlistLength; itemIndex++)
			{
				var itemId = itemlist[itemIndex];
				if (keywordResultObj.hasOwnProperty(itemId))
				{
					CatTotalCnt += keywordResultObj[itemId].count;
					TotalResult += keywordResultObj[itemId].result
				}
			}

			TotalCnt += CatTotalCnt;
			console.log("[CheckKeyword] Catlimit : " + Catlimit + " CatTotalCnt : " + CatTotalCnt);

			if (Catlimit <= CatTotalCnt)
			{
				bCatAllow = false;
			}
		}	
		
		console.log("[CheckKeyword] keywordcnt : " + keywordcnt + " TotalCnt : " + TotalCnt);

		if (keywordcnt <= TotalCnt)
		{
			bTotalAllow = false;
		}

		
		if (keywordscope == 2) // KEYWORD_SCOPE_TOTAL
		{
			bAllow = bTotalAllow;
		}
		else if (keywordscope == 1) // KEYWORD_SCOPE_CATEGORY
		{
			bAllow = bCatAllow;
		}
		else // if (keywordscope == 0) // KEYWORD_SCOPE_ALL
		{
			bAllow = bCatAllow || bTotalAllow;
		}

		console.log("[CheckKeyword] keywordscope : " + keywordscope + " bTotalAllow : " + bTotalAllow + " bCatAllow : " + bCatAllow + " bAllow : " + bAllow);
		if (bAllow == false)
		{
			return {"bAllow" : false, "KeywordTotal" : TotalCnt, "KeywordResult" : TotalResult};
		}
	}

	return {"bAllow" : true, "KeywordTotal" : 0, "KeywordResult" : ""};
}


export function GetGWReactionResultObj(Action, keywordResultObj)
{
	var LogObj = {"bAllow" : true};
	var SaveCopyObj = {"bAllow" : true};
	var WarnObj = {"bAllow" : true};
	var BlockObj = {"bAllow" : true};

	if (Action.BLOCK)
	{
		BlockObj = CheckKeyword(Action.BLOCK.keywordcnt, Action.BLOCK.keywordscope, Action.BLOCK.keywordcatlist, keywordResultObj);
	}

	if (BlockObj.bAllow == true)
	{
		if (Action.LOG)
		{	
			LogObj = CheckKeyword(Action.LOG.keywordcnt, Action.LOG.keywordscope, Action.LOG.keywordcatlist, keywordResultObj);
			if (LogObj.bAllow == false)
			{
				SaveCopyObj.bAllow = false;
			}
		}

		if (Action.WARN)
		{
			WarnObj = CheckKeyword(Action.WARN.keywordcnt, Action.WARN.keywordscope, Action.WARN.keywordcatlist, keywordResultObj);
		}
	}	

	var RetObj = {"block" : BlockObj.bAllow == false, "Log" : LogObj.bAllow == false, "SaveCopy" : SaveCopyObj.bAllow == false, "Warn" : WarnObj.bAllow == false};
	if (BlockObj.bAllow == false)
	{
		RetObj["keywordResult"] = BlockObj.KeywordResult;
		RetObj["keywordTotal"] = BlockObj.KeywordTotal;
	}
	else if (LogObj.bAllow == false)
	{
		RetObj["keywordResult"] = LogObj.KeywordResult;
		RetObj["keywordTotal"] = LogObj.KeywordTotal;
	}
	else
	{
		RetObj["keywordResult"] = "";
		RetObj["keywordTotal"] = 0;
	}

	if (WarnObj.bAllow == false)
	{
		RetObj["keywordResultWarn"] = WarnObj.KeywordResult;
		RetObj["keywordTotalWarn"] = WarnObj.KeywordTotal;
	}
	
	return RetObj;
}

import * as keyword from './keyword.js';
import * as stringview from './stringview.js';
import * as xml2json from './xml2json.js';
import {PolicyObj} from './background.js';