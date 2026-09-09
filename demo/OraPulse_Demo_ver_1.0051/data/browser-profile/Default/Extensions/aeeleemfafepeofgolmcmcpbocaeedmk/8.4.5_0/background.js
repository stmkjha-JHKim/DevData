var port_;
var map_ = new map.Map();
var FindMap_ = new map.Map();
var urlcontrol_type_;
var sBlockRedirectURL;
var bRedirect;
var TempPolicyMap_ = new map.Map();

export var PolicyObj;

const ABOUT_BLANK_STR = "about:blank";
var PopupTabID_SourceURLMap = new map.Map();

var classObject = 
{
	initializeHost: function()
	{
		port_ = chrome.runtime.connectNative('com.bluemoonsoft.dlp');

		port_.onMessage.addListener(function(response) {
			console.log("onMessage.addListener Start!!");
			if (chrome.runtime.lastError) 
			{
				console.log("error: " + chrome.runtime.lastError.message);
			} 
			else
			{
				console.log("GRADIUS Extension Start");
				bRedirect = false;
				if (response.type != undefined && response.type.length != 0)
				{
					urlcontrol_type_ = response.type;
					console.log("urlcontrol_type_=" + urlcontrol_type_);
				}

				if(response.ControlURLs != undefined && response.ControlURLs.length != 0)
				{
					var url_lists = response.ControlURLs.split(";");
					//console.log("url_lists " + url_lists);
					map_.clear();
					FindMap_.clear();
					for(var i=1; i<url_lists.length; i++)
					{
						var url_list = url_lists[i].toLowerCase();
						if (url_list != "")
						{
							if (url_list.indexOf("*") >= 0)
							{
								var find_in_url_list = url_list.substring(1, url_list.length);
								//console.log("find_in_url_list=" + find_in_url_list);
								FindMap_.put(find_in_url_list, "");
							}
							else
							{
								map_.put(url_list, "");
							}
						}
					}					
					console.log("url_lists count=" + url_lists.length - 1);
				}

				if(response.BlockRedirectURL != undefined && response.BlockRedirectURL.length != 0)
				{
					sBlockRedirectURL = response.BlockRedirectURL;
					bRedirect = true;
					//console.log("sBlockRedirectURL=" + sBlockRedirectURL + " bRedirect=" + bRedirect);
				}

				if(response.TempPolicyURLs != undefined && response.TempPolicyURLs.length != 0)
				{
					url_lists = response.TempPolicyURLs.split(";");
					//console.log("url_lists " + url_lists);
					TempPolicyMap_.clear();
					for(var i=1; i<url_lists.length; i++)
					{
						url_list = url_lists[i].toLowerCase();
						if (url_list != "")
						{
							TempPolicyMap_.put(url_list, "");
						}
					}					
					console.log("url_lists count=" + url_lists.length - 1);
				}

				PolicyObj = response;
				console.log(PolicyObj);

				chrome.management.getAll(function(result){
					//console.log(result);
					for (var extension of result)
					{
						//console.log(extension);
						if (extension.mayEnable == false)
						{
							console.log(extension.name + "(" + extension.id + ")");
						}
					}
				});
			}
		});
		  
		port_.onDisconnect.addListener(function() {
			console.log("Disconnected");
			classObject.initializeHost ();
			port_.postMessage({"text":"#POLICY#"});
		});
	},
	
	onActiveTab: function (activeInfo)
	{
		chrome.tabs.get (activeInfo.tabId, function (tab) {
			console.log (tab.url);
			/*if (tab.url.indexOf("https://") >= 0)
			{*/
				var url = common.getHostFromURL(tab.url);
				if (url.hostname == "")
				{
					url.hostname = "Unknown";
				}
				port_.postMessage ({"ACTIVE_URL" : tab.url, "hosturl" : url.hostname, "title" : tab.title});
				console.log ({"ACTIVE_URL" : tab.url, "hosturl" : url.hostname, "title" : tab.title});
			//}
		})
	},
	
	onUpdateTab: function (tabId, changeInfo, tab)
	{
		chrome.windows.get (tab.windowId, { populate: true }, function (window) {
			if (window.focused)
			{
				//console.log(changeInfo);
				if (tab.active)
				{
					// URL이 변경된 경우
					if (changeInfo.hasOwnProperty("url"))
					{
						var url = common.getHostFromURL(changeInfo.url);
						if (url.hostname == "")
						{
							url.hostname = "Unknown";
						}
						port_.postMessage ({"ACTIVE_URL" : changeInfo.url, "hosturl" : url.hostname, "title" : tab.title});
						console.log({"ACTIVE_URL" : changeInfo.url, "hosturl" : url.hostname, "title" : tab.title});
					}

					// URL이 변경된 경우
					if (changeInfo.hasOwnProperty("title"))
					{
						var url = common.getHostFromURL(tab.url);
						if (url.hostname == "")
						{
							url.hostname = "Unknown";
						}
						port_.postMessage ({"ACTIVE_URL" : tab.url, "hosturl" : url.hostname, "title" : changeInfo.title});
						console.log({"ACTIVE_URL" : tab.url, "hosturl" : url.hostname, "title" : changeInfo.title});
					}
				}

			}
		})
		
		//console.log("[onUpdateTab] changeInfo : %o",changeInfo);	
		if (changeInfo && changeInfo.status == "loading")
		{
			if (changeInfo.url && changeInfo.url.indexOf("https://") == 0)
			{
				chrome.webNavigation.getAllFrames({tabId: tabId}, function (arrFrame) {
					if (arrFrame)
					{
						//console.log("[onUpdateTab] arrFrame : length : %d\r\n%o", arrFrame.length, arrFrame);
						for (var i = 0; i < arrFrame.length; i++)
						{
							//console.log("[onUpdateTab] errorOccurred : %o, arrFrame[i].frameType : %s", arrFrame[i].errorOccurred, arrFrame[i].frameType);
							//console.log("[onUpdateTab] url: %s", arrFrame[i].url);
							if (arrFrame[i].errorOccurred == false && arrFrame[i].frameType == "outermost_frame")
							{
								var frameURL = arrFrame[i].url.toLowerCase();
								var url = common.getHostFromURL(frameURL);
								if (classObject.isWebSiteBlock(url))
								{
									console.log("[onUpdateTab] #WEBSITE_BLOCK#");
									port_.postMessage({"text":"#WEBSITE_BLOCK#", "url" : frameURL, "hosturl" : url.hostname});
									chrome.tabs.discard(tabId);
								}
							}
						}
					}
				});
			}
		}
	},
	
	onWindowActive: function (windowId)
	{
		if ((windowId != chrome.windows.WINDOW_ID_NONE) && (windowId != chrome.windows.WINDOW_ID_CURRENT))
		{
			chrome.extension.isAllowedIncognitoAccess (function (isAllowedAccess) {
				if (!isAllowedAccess)
				{
					//console.log ({"ACTIVE_URL" : "Unknown"});
					port_.postMessage ({"ACTIVE_URL" : "Unknown"});
				}
			});

			chrome.windows.getCurrent({populate: true}, function(currentWindow) {
				chrome.tabs.query({currentWindow: true, active: true}, function(tabs) {
					var currentTab = currentWindow.tabs.filter(function(tab) {
						return tab.active;
					})[0];
	
					console.log("2. onWindowActive Tab id : " + currentTab.id + ", url : "+ currentTab.url);
					if (currentTab.url == ABOUT_BLANK_STR)
					{
						console.log("2. onWindowActive Source Tab id : " + currentTab.id);
						currentTab.url = classObject.findTabURL(currentTab.id, currentTab.url);
						console.log("2. onWindowActive UpdateURL: " + currentTab.url);
					}

					var url = common.getHostFromURL(currentTab.url);
					if (url.hostname == "")
					{
						url.hostname = "Unknown";
					}
					console.log({"ACTIVE_URL" : currentTab.url, "hosturl" : url.hostname, "title" : currentTab.title});
					port_.postMessage ({"ACTIVE_URL" : currentTab.url, "hosturl" : url.hostname, "title" : currentTab.title});
				})
			});
		}
	},
	
	onDisabled: function(info)
	{
		//chrome.management.setEnabled("befafhehepoikdmllhkbndipoeifhbgm", true, null);
		console.log (info.id + " disabled");
	},
	
	onUninstalled: function(id)
	{
		//chrome.management.launchApp("befafhehepoikdmllhkbndipoeifhbgm");
		console.log ("extension with id uninstalled" + id); 
	},

	onBeforeRequest: function(details)
	{
		if ((details.url.indexOf("https://") < 0)
			|| (!PolicyObj) ) return { cancel: false };
		//console.log("{details}");
		console.log(details);
		if (common.IsPassHost(details.url))
		{
			port_.postMessage({"text":"PassHost!!", "url" : details.url, "method" : details.method, "type" : details.type});
			return { cancel: false };
		}

		port_.postMessage({"text":"onBeforeRequest....", "url" : details.url, "method" : details.method, "type" : details.type});
		var cancle_ret = false;
		if (details.requestBody /*details.method == "POST"*/)
		{
			if (PolicyObj.WEBMAIL || PolicyObj.WEBINPUT || PolicyObj.GW_WEBMAIL || PolicyObj.WORKWRITE)
			{
				console.log("Post Data Parsing Start!!");
				var postDataObj = common.GetPacketData(details);
				if (postDataObj == "requestBodyUndefined")
				{
					//console.log("postDataObj == undefined");
					return { cancel : cancle_ret };
				}
				var mailData = common.GetWebMailBodyData(postDataObj, details.url);
				port_.postMessage({"text":"#PostData#", "postData" : postDataObj});
				if (mailData.bodyData && mailData.bodyData != "undefined")// WEBMAIL
				{
					if (PolicyObj.GW_WEBMAIL && (common.CheckCategory(PolicyObj.GW_WEBMAIL.URL, 1, details.url) == true))
					{
						cancle_ret = classObject.isWebMailBlock(postDataObj, mailData, details, PolicyObj.GW_WEBMAIL, true);
					}
					else if (PolicyObj.WEBMAIL)
					{
						cancle_ret = classObject.isWebMailBlock(postDataObj, mailData, details, PolicyObj.WEBMAIL, false);
					}
				}
				else if (PolicyObj.WEBINPUT || PolicyObj.WORKWRITE)
				{
					if (PolicyObj.WORKWRITE && (common.CheckCategory(PolicyObj.WORKWRITE.URL, 1, details.url) == true))
					{
						cancle_ret = classObject.isWebInputBlockDetail(postDataObj, details, PolicyObj.WORKWRITE, true);
					}
					else if (PolicyObj.WEBINPUT)
					{
						if (PolicyObj.WEBINPUT.DetailLog == true)
						{
							cancle_ret = classObject.isWebInputBlockDetail(postDataObj, details, PolicyObj.WEBINPUT, false);
						}
						else
						{
							cancle_ret = classObject.isWebInputBlock(postDataObj, details);
						}
					}
				}
			}
		
			return { cancel : cancle_ret };
		}	
		else //if (details.method == "GET")
		{
			//console.log("fullurl =" + details.url);
			var url = common.getHostFromURL(details.url);
			if(url.hostname != "")
			{
				cancle_ret = classObject.isWebSiteBlock(url);
				if (cancle_ret == true)
				{
					console.log("[OnBeforeRequest] #WEBSITE_BLOCK#");
					port_.postMessage({"text":"#WEBSITE_BLOCK#", "url" : details.url, "hosturl" : url.hostname});
					if (bRedirect == true)
					{
						chrome.tabs.query({currentWindow: true, active: true}, function (tab) {
							chrome.tabs.update(tab.id, {url: sBlockRedirectURL});
						});

						/*
						chrome.tabs.query({currentWindow: true, active: true}, function (tab) {
							chrome.tabs.update(tab.id, {url: "blocked.html"});
						});
						*/
					}
				}
				else if (details.type == "xmlhttprequest")
				{
					if (PolicyObj.WEBINPUT && PolicyObj.WEBINPUT.DetailLog == true)
					{
						cancle_ret = classObject.isWebInputBlockXmlhttprequest(details.url);
					}
				}
			}
			return { cancel : cancle_ret };
			
		}
		if(url.domain != "")
		{
			console.log("map.domain=" + map_.get(url.domain));
			if(map_.get(url.domain) != undefined) return { cancel: true };
		}
		console.log("[onBeforeRequest] end");
		
		return { cancel: false };
	},
	
	onCreatedNavigationTarget: function (details)
	{
		console.log("1. onCreatedNavigationTarget tabId : " + details.tabId + ", url : "+ details.url);
		
		if (details.url == ABOUT_BLANK_STR)
		{
			chrome.tabs.get(details.sourceTabId, function (tab) {
				PopupTabID_SourceURLMap.put(details.tabId, tab.url);
				console.log("1. get tabId : " + details.tabId + ",  url : "+ PopupTabID_SourceURLMap.get(details.tabId));
			});
		}
	},
	
	onRemoved: function (tabId, removeInfo)
	{
		if (PopupTabID_SourceURLMap.get(tabId) != undefined)
		{
			console.log("3. Remove PopupTabSourceURLMap : " + tabId);
			PopupTabID_SourceURLMap.remove(tabId);
		}
	},
		
	isWebSiteBlock: function(url)
	{
		var bRet = false;
		var match = false;
		//console.log("map.hostname=" + map_.get(url.hostname));
				
		var hostURL = url.hostname.toLowerCase();
		var domainURL = url.domain.toLowerCase();
		var fullURL = hostURL + url.suburl.toLowerCase();

		//console.log("hostURL=" + hostURL + " domainURL=" + domainURL + " fullURL=" + fullURL);

		if (url.hostname != "" && TempPolicyMap_.get(hostURL) != undefined)
			match = true;
		if (url.domain != "" && TempPolicyMap_.get(domainURL) != undefined)
			match = true;

		if (match == true)
		{
			console.log("Find TempPolicyMap_");
			return bRet;
		}

		if (url.hostname != "" && map_.get(hostURL) != undefined)
			match = true;
		if (url.domain != "" && map_.get(domainURL) != undefined)
			match = true;
		if (url.suburl != "" && map_.get(fullURL) != undefined)
			match = true;

		var FindURLKeys = FindMap_.keys();
		var FindURLKeysLength = FindURLKeys.length;
		//console.log("FindURLKeysLength=" + FindURLKeysLength);
		for (var nCnt = 0; nCnt < FindURLKeysLength; nCnt++)
		{
			var FindURLKey = FindURLKeys[nCnt];
			//console.log("FindURLKey=" + FindURLKey);
			if (hostURL.indexOf(FindURLKey) >= 0 || domainURL.indexOf(FindURLKey) >= 0 || fullURL.indexOf(FindURLKey) >= 0)
			{
				match = true;
				break;
			}
		}

		if (urlcontrol_type_ == '0' && match == true) // ��ü ��� ������ ����
		{
			console.log("Block(1) - hostname=" + url.hostname + ", domain=" + url.domain);
			bRet = true;
		}
		else if (urlcontrol_type_ == '1' && match == false) // ��ü ���� ������ ���
		{
			console.log("Block(2) - hostname=" + url.hostname + ", domain=" + url.domain);
			bRet = true;
		}

		return bRet;
	},
		
	findTabURL: function(tabID, currentURL)
	{
		var sourceURL = PopupTabID_SourceURLMap.get(tabID);
		console.log("2-1. findTabURL : " + sourceURL);
		if (sourceURL != undefined)
		{
			currentURL = sourceURL;
		}
		
		return currentURL;
	},
	
	isWebMailBlock: function(postDataObj, mailData, details, actionObj, gwMail)
	{
		var bRet = false;
		var analysisData = mailData.bodyData;
		console.log("Data : " + analysisData);
		
		if (PolicyObj.PVersion && Number(PolicyObj.PVersion) >= 1.2)
		{
			var keywordResultObj;
			var ReactionResultObj;
			if (gwMail == true)
			{
				keywordResultObj = common.GetKeywordResultObj(PolicyObj.KeywordSettingsALL, actionObj.Keyworditemlist, actionObj.ExceptionKeywordSettings, analysisData);
				ReactionResultObj = common.GetGWReactionResultObj(actionObj, keywordResultObj);
			}
			else
			{
				keywordResultObj = common.GetKeywordResultObj(PolicyObj.KeywordSettingsALL, actionObj.Keyworditemlist, PolicyObj.ExceptionKeywordSettings, analysisData);
				ReactionResultObj = common.GetReactionResultObj(actionObj, details.url, keywordResultObj);
			}
			
			if (ReactionResultObj.Log == true || ReactionResultObj.block == true || ReactionResultObj.Warn == true)
			{
				console.log("최종 메일 로깅 :" + ReactionResultObj.Log + ", 차단 : " + ReactionResultObj.block + ", 경고 : " + ReactionResultObj.Warn);
				port_.postMessage({"text": "#WEBMAIL#", "url" : details.url, "mailData" : mailData, "postData" : JSON.stringify(postDataObj), "gwMail" : gwMail, ...ReactionResultObj});
			}

			bRet = ReactionResultObj.block;
		}
		else
		{
			var keywordObj;
			var ReactionObj;
			if (gwMail == true)
			{
				keywordObj = common.GetKeywordObj(actionObj.KeywordSettings, actionObj.ExceptionKeywordSettings, analysisData);
				ReactionObj = common.GetGWReaction(actionObj, keywordObj.KeywordTotal);
			}
			else
			{
				keywordObj = common.GetKeywordObj(PolicyObj.KeywordSettings, PolicyObj.ExceptionKeywordSettings, analysisData);
				ReactionObj = common.GetReaction(actionObj, details.url, keywordObj.KeywordTotal);
			}
		
			if (ReactionObj.bLog == true || ReactionObj.bBlock == true || ReactionObj.bWarn == true)
			{
				console.log("최종 메일 로깅 :" + ReactionObj.bLog + ", 차단 : " + ReactionObj.bBlock + ", 경고 : " + ReactionObj.bWarn);
				port_.postMessage({"text":"#WEBMAIL#", "url" : details.url, "mailData" : mailData, "postData" : JSON.stringify(postDataObj), "keywordResult" : keywordObj.KeywordResult, "keywordTotal" : keywordObj.KeywordTotal, "block" : ReactionObj.bBlock, "Log" : ReactionObj.bLog, "SaveCopy" : ReactionObj.bSaveCopy, "Warn" : ReactionObj.bWarn, "gwMail" : gwMail});
			}

			bRet = ReactionObj.bBlock;
		}

		return bRet;
	},
		
	isWebInputBlock: function(object, details)
	{
		var bRet = false;

		var checkValueMatch = common.IsCheckValueMatch(details);
		var contents = common.getWebInputData(object, checkValueMatch);
		if (contents != "")
		{
			console.log("isWebInputBlock Start");
			console.log(contents);
			
			if (PolicyObj.PVersion && Number(PolicyObj.PVersion) >= 1.2)
			{
				var keywordResultObj = common.GetKeywordResultObj(PolicyObj.KeywordSettingsALL, PolicyObj.WEBINPUT.Keyworditemlist, PolicyObj.ExceptionKeywordSettings, contents);
				var ReactionResultObj = common.GetReactionResultObj(PolicyObj.WEBINPUT, details.url, keywordResultObj);		
				if (ReactionResultObj.Log == true || ReactionResultObj.block == true || ReactionResultObj.Warn == true)
				{
					console.log("최종 웹입력 로깅 :" + ReactionResultObj.Log + ", 차단 : " + ReactionResultObj.block + ", 경고 : " + ReactionResultObj.Warn);
					port_.postMessage({"text": "#WEBINPUT#", "url" : details.url, "contents" : contents, ...ReactionResultObj});
				}

				bRet = ReactionResultObj.block;
			}
			else
			{
				var keywordObj = common.GetKeywordObj(PolicyObj.KeywordSettings, PolicyObj.ExceptionKeywordSettings, contents);
				var ReactionObj = common.GetReaction(PolicyObj.WEBINPUT, details.url, keywordObj.KeywordTotal);
				if (ReactionObj.bLog == true || ReactionObj.bBlock == true || ReactionObj.bWarn == true)
				{
					console.log("최종 웹입력 로깅 :" + ReactionObj.bLog + ", 차단 : " + ReactionObj.bBlock + ", 경고 : " + ReactionObj.bWarn);
					port_.postMessage({"text":"#WEBINPUT#", "url" : details.url, "contents" : contents, "keywordResult" : keywordObj.KeywordResult, "keywordTotal" : keywordObj.KeywordTotal, "block" : ReactionObj.bBlock, "Log" : ReactionObj.bLog, "SaveCopy" : ReactionObj.bSaveCopy, "Warn" : ReactionObj.bWarn});
				}

				bRet = ReactionObj.bBlock;
			}
		}
		
		return bRet;
	},
	
	isWebInputBlockDetail: function(object, details, actionObj, wwInput)
	{
		var bRet = false;
		
		var contents = common.GetWebInputBodyData(object, details.url);
		if (!!contents)
		{
			console.log("isWebInputBlockDetail Start");
			console.log(contents);

			if (PolicyObj.PVersion && Number(PolicyObj.PVersion) >= 1.2)
			{
				var keywordResultObj = common.GetKeywordResultObj(PolicyObj.KeywordSettingsALL, actionObj.Keyworditemlist, PolicyObj.ExceptionKeywordSettings, contents);
				var ReactionResultObj = common.GetReactionResultObj(actionObj, details.url, keywordResultObj);
				
				if (ReactionResultObj.Log == true || ReactionResultObj.block == true || ReactionResultObj.Warn == true)
				{
					console.log("최종 웹입력 로깅 :" + ReactionResultObj.Log + ", 차단 : " + ReactionResultObj.block + ", 경고 : " + ReactionResultObj.Warn);
					port_.postMessage({"text": "#WEBINPUT#", "url" : details.url, "contents" : contents, "wwInput" : wwInput, ...ReactionResultObj});
				}
				bRet = ReactionResultObj.block;
			}
			else
			{
				var keywordObj = common.GetKeywordObj(PolicyObj.KeywordSettings, PolicyObj.ExceptionKeywordSettings, contents);
				var ReactionObj = common.GetReaction(actionObj, details.url, keywordObj.KeywordTotal);
				
				if (ReactionObj.bLog == true || ReactionObj.bBlock == true || ReactionObj.bWarn == true)
				{
					console.log("최종 웹입력 로깅 :" + ReactionObj.bLog + ", 차단 : " + ReactionObj.bBlock + ", 경고 : " + ReactionObj.bWarn);
					port_.postMessage({"text":"#WEBINPUT#", "url" : details.url, "contents" : contents, "keywordResult" : keywordObj.KeywordResult, "keywordTotal" : keywordObj.KeywordTotal, "block" : ReactionObj.bBlock, "Log" : ReactionObj.bLog, "SaveCopy" : ReactionObj.bSaveCopy, "Warn" : ReactionObj.bWarn, "wwInput" : wwInput});
				}
				bRet = ReactionObj.bBlock;
			}
		}
		
		return bRet;
	},
		
	isWebInputBlockXmlhttprequest: function(url)
	{
		var bRet = false;

		var contents = common.GetWebInputBodyDataXmlhttprequest(url);
		if (!!contents)
		{
			console.log("isWebInputBlockXmlhttprequest Start");
			console.log(contents);

			if (PolicyObj.PVersion && Number(PolicyObj.PVersion) >= 1.2)
			{
				var keywordResultObj = common.GetKeywordResultObj(PolicyObj.KeywordSettingsALL, PolicyObj.WEBINPUT.Keyworditemlist, PolicyObj.ExceptionKeywordSettings, contents);
				var ReactionResultObj = common.GetReactionResultObj(PolicyObj.WEBINPUT, url, keywordResultObj);
				
				if (ReactionResultObj.Log == true || ReactionResultObj.block == true || ReactionResultObj.Warn == true)
				{
					console.log("최종 웹입력 로깅 :" + ReactionResultObj.Log + ", 차단 : " + ReactionResultObj.block + ", 경고 : " + ReactionResultObj.Warn);
					port_.postMessage({"text": "#WEBINPUT#", "url" : url, "contents" : contents, ...ReactionResultObj});
				}

				bRet = ReactionResultObj.block;
			}
			else
			{
				var keywordObj = common.GetKeywordObj(PolicyObj.KeywordSettings, PolicyObj.ExceptionKeywordSettings, contents);
				var ReactionObj = common.GetReaction(PolicyObj.WEBINPUT, url, keywordObj.KeywordTotal);
				if (ReactionObj.bLog == true || ReactionObj.bBlock == true || ReactionObj.bWarn == true)
				{
					console.log("최종 웹입력 로깅 :" + ReactionObj.bLog + ", 차단 : " + ReactionObj.bBlock + ", 경고 : " + ReactionObj.bWarn);
					port_.postMessage({"text":"#WEBINPUT#", "url" : url, "contents" : contents, "keywordResult" : keywordObj.KeywordResult, "keywordTotal" : keywordObj.KeywordTotal, "block" : ReactionObj.bBlock, "Log" : ReactionObj.bLog, "SaveCopy" : ReactionObj.bSaveCopy, "Warn" : ReactionObj.bWarn});
				}

				bRet = ReactionObj.bBlock;
			}
		}
		
		return bRet;
	}

};

classObject.initializeHost();
port_.postMessage({"text":"#POLICY#"});

chrome.management.onDisabled.addListener(
	classObject.onDisabled
);

chrome.management.onUninstalled.addListener(
	 classObject.onUninstalled
);

chrome.tabs.onActivated.addListener(
	classObject.onActiveTab
);

chrome.tabs.onUpdated.addListener(
	classObject.onUpdateTab
);

chrome.windows.onFocusChanged.addListener(
	classObject.onWindowActive
);

chrome.webRequest.onBeforeRequest.addListener(
	classObject.onBeforeRequest,{urls: ["<all_urls>"]}, ["blocking", "requestBody"]
);

chrome.webNavigation.onCreatedNavigationTarget.addListener(
	classObject.onCreatedNavigationTarget
);

chrome.tabs.onRemoved.addListener(
	classObject.onRemoved
);

import * as common from './common.js';
import * as map from './map.js';