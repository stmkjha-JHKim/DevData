export function IsKeywordPattern(finddata, keywordtype)
{
	var bRet = false;
	if (keywordtype == "S" || keywordtype == "KS" || keywordtype == "FS")
	{
		var data = finddata[0].replace(/\D/g,"");

		// 내국인 생년월일 검사
		var domesticpattern = /(\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[1,2][0-9]|3[0,1]))[1-4][0-9]{6}/;
		// 외국인 생년월일 검사
		var foreignerpattern = /(\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[1,2][0-9]|3[0,1]))[5-8][0-9]{6}/;

		// 2월 30일, 31일의 경우 예외 처리하자
		if (data[2] == 0 && data[3] == 2 && data[4] > 2) // 2월인데 30일을 표시하는 경우
		{
			console.log("[IsKeywordPattern] 2월 날짜 맞지 않음 = " + finddata[0]);
			return bRet;
		}
		if (domesticpattern.test(data) == true)
		{
			if (keywordtype != "FS")
			{
				bRet = ResidentNumberValidCheck(data, true);
			}
		}
		else if (foreignerpattern.test(data) == true)
		{
			if (keywordtype != "KS")
			{
				bRet = ResidentNumberValidCheck(data, false);
			}
		}
		else
		{
			console.log("[IsKeywordPattern] not match pattern = " + finddata[0]);
		}

		
	}
	else if (keywordtype == "T")
	{
		var TelNumObject = {"data" : finddata[0], "charindex" : -1, "datalen" : -1};
		common.OnlyNumFilterNGetCharPos(TelNumObject);
		//console.log(TelNumObject);
		
		var pattern_seoul = /^0(?:2)[2-9]/;
		var pattern_etc = /^0(?:3[1-3]|4[1-4]|5[1-5]|6[2-4]|70)[2-9]/;
		
		//서울 지역번호 
		if (pattern_seoul.test(TelNumObject.data) == true)
		{
			if (TelNumObject.charindex != 3 && (TelNumObject.datalen == 9 || TelNumObject.datalen == 10))
			{
				bRet = true;
			}
		}
		//수도권, 지방 지역번호
		else if (pattern_etc.test(TelNumObject.data) == true)
		{
			if (TelNumObject.charindex != 2 && (TelNumObject.datalen == 10 || TelNumObject.datalen == 11))
			{
				bRet = true;
			}
		}
		
		if (bRet == false)
		{
			console.log("[IsKeywordPattern] not match pattern = " + finddata[0]);
		}
	}
	else if (keywordtype == "E")
	{
		var pattern = /.kr$|.com$|.net$|.edu$|.org|.gov$|.biz$|.int$|.co.|.or.|.ac.|.go.|.pe./;
		if (pattern.test(finddata[0]) == true)
		{
			bRet = true;
		}
		else
		{
			console.log("[IsKeywordPattern] not match pattern = " + finddata[0]);
		}
	}
	else if (keywordtype == "P")
	{
		var pattern = /[M|S|G|D]\d{3}[\d|A-Z]\d{4}/;
		if (pattern.test(finddata[0]) == true)
		{
			bRet = true;
		}
		else
		{
			console.log("[IsKeywordPattern] not match pattern = " + finddata[0]);
		}
	}
	else if (keywordtype == "D")
	{
		var pattern = /(1[1-9]|2[0-6|8]|서울|경기|부산|강원|충북|충남|전북|전남|경북|경남|제주|대구|인천|광주|대전|울산)\D\d{2}\D\d{6}\D\d{2}/;
		//var pattern = /[11-26|서울|경기|부산|강원|충북|충남|전북|전남|경북|경남|제주|대구|인천|광주|대전|울산]\D\d{2}\D\d{6}\D\d{2}/;
		if (pattern.test(finddata[0]) == true)
		{
			bRet = true;
		}
		else
		{
			console.log("[IsKeywordPattern] not match pattern = " + finddata[0]);
		}
	}
	else if (keywordtype == "M")
	{
		var pattern = /^01[0-1|6-9]/;
		if (pattern.test(finddata[0]) == true)
		{
			bRet = true;
		}
		else
		{
			console.log("[IsKeywordPattern] not match pattern = " + finddata[0]);
		}

		/*
		var pattern = /01[0-1|6-9]\D\d{3,4}\D\d{4}/;
		if (pattern.test(finddata[0]) == true)
		{
			bRet = true;
		}
		else
		{
			console.log("[IsKeywordPattern] not match pattern = " + finddata[0]);
		}
		*/
	}
	else if (keywordtype == "C")
	{
		var data = finddata[0].replace(/\D/g,"");

		var cardNumSum = 0;
		var checkDigit = 0;

		if (data.length != 16)
		{
			return false;
		}

		var digits = data.split('');
		for (var i = 0; i < digits.length; i++)
		{
			digits[i] = parseInt(digits[i], 10);
		}

		if (digits[0] >=3 && digits[0] <= 6)
		{
			var alt = false;
			for (var j = 0; j < digits.length-1; j++)
			{
				var temp = 0;
				if (j % 2 == 0)
				{
					temp = digits[j] *2;
				}
				else
				{
					temp = digits[j];
				}

				if (temp >= 10)
				{
					cardNumSum += parseInt(temp/10, 10);
					cardNumSum += parseInt(temp%10, 10);
				}
				else
				{
					cardNumSum += temp;
				}
			}

			checkDigit = 10 - (cardNumSum % 10);
			if (checkDigit == 10)
			{
				checkDigit = 0
			}

			if (digits[15] == checkDigit)
			{
				bRet = true;
			}
		}
		else if (digits[0] == 9)
		{
			var domesticCreditCardPattern = /\b94(?:09|1[1,5]|3[5-6]|45|51|6[1|5-6]|\d0)/;
			if (domesticCreditCardPattern.test(data) == true)
			{
				bRet = true;
			}
			else
			{
				console.log("[IsKeywordPattern] domestic card invalid : " + data);
			}
		}
	}
	else if (keywordtype == "N")
	{
		bRet = true;
	}

	return bRet;
}

export function ResidentNumberValidCheck(data, domestic)
{
	// 유효성 검사
	var tempdata = data;
	var tempSum =0;
	var j = 2;
	
	for (var i=0; i < tempdata.length-1; i++)
	{
		tempSum += tempdata[i] * j++;
		if (j == 10)
		{
			j = 2;
		}
	}

	if (domestic == true)
	{
		if ((11-(tempSum%11))%10 == tempdata[12])
		{
			return true;
		}
	}
	else
	{
		if ((11-(tempSum%11)%10+2)%10 == tempdata[12])
		{
			return true;
		}
		
	}

	console.log("[IsKeywordPattern] not validate = " + data);

	return false;
}

export function IsExceptKeywordPattern(Result, ExceptionKeyword)
{
	if (ExceptionKeyword == null)
	{
		return false;
	}

	var bRet = false;
	var Length = ExceptionKeyword.length;
	for (var Index = 0; Index < Length; Index++)
	{
		if (ExceptionKeyword[Index].position == "0")
		{
			if (Result.indexOf(ExceptionKeyword[Index].pattern) == 0)
			{
				bRet = true;
			}
		}
		else if (ExceptionKeyword[Index].position == "1")
		{
			if (Result.indexOf(ExceptionKeyword[Index].pattern) >= 0)
			{
				bRet = true;
			}
		}
	}

	return bRet;
}

import * as common from './common.js';