# -*- coding: utf-8 -*-
"""
A Translation module.

You can translate text using aiohttp in this module.

Copyright (c) 2022 Ben Z

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
"""
import asyncio
import functools
import json
import random
import typing

import aiohttp

from aiogtrans import urls
from aiogtrans.constants import (
    DEFAULT_CLIENT_SERVICE_URLS,
    DEFAULT_FALLBACK_SERVICE_URLS,
    DEFAULT_RAISE_EXCEPTION,
    DEFAULT_USER_AGENT,
    LANGCODES,
    LANGUAGES,
    SPECIAL_CASES,
)
from aiogtrans.models import Detected, Translated, TranslatedPart

EXCLUDES = ("en", "ca", "fr")

RPC_ID = "MkEWBc"


class AiohttpTranslator:
    """
    Google Translate Ajax API Translator class

    Create an instance of this class to access the API.
    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop = asyncio.get_event_loop(),
        session: aiohttp.ClientSession = None,
        service_urls: typing.Union[list, tuple] = DEFAULT_CLIENT_SERVICE_URLS,
        user_agent: str = DEFAULT_USER_AGENT,
        raise_exception: bool = DEFAULT_RAISE_EXCEPTION,
        timeout: typing.Union[int, float] = 60.0,
        use_fallback: bool = False,
    ) -> None:
        """
        Initiating the client with the given parameters.

        Loop is the asyncio event loop to use.
        Session is the aiohttp client session to use.
        ServiceUrls is the list of service urls to use.
        UserAgent is the user agent to use.
        RaiseException is whether to raise an exception when an error occurs.
        Timeout is the timeout to use for the requests.
        UseFallback is whether to use the fallback service urls if the main service urls fail.
        """

        self.loop = loop
        self.raise_exception = raise_exception

        if use_fallback:
            self.service_urls = DEFAULT_FALLBACK_SERVICE_URLS
            self.client_type = "gtx"
        else:
            self.service_urls = service_urls
            self.client_type = "tw-ob"

        if not session:
            headers = {
                "User-Agent": user_agent,
                "Referer": "https://translate.google.com",
            }

            self.session = loop.run_until_complete(
                self._create_session(loop, headers, aiohttp.ClientTimeout(total=timeout))
            )

        else:
            self.session = session

    async def _create_session(
        self,
        loop: asyncio.AbstractEventLoop,
        headers: dict,
        timeout: aiohttp.ClientTimeout,
    ) -> aiohttp.ClientSession:
        """
        Internal method to create an aiohttp client session to use for requests
        """
        session = await aiohttp.ClientSession(
            loop=loop, headers=headers, timeout=timeout
        )
        return session

    async def _build_rpc_request(self, text: str, dest: str, src: str) -> str:
        """
        Build the rpc request
        """
        trans_info = await self.loop.run_in_executor(
            None,
            functools.partial(
                json.dumps, obj=[[text, src, dest, True], [None]], separators=(",", ":")
            ),
        )
        rpc = await self.loop.run_in_executor(
            None,
            functools.partial(
                json.dumps,
                obj=[
                    [
                        [
                            RPC_ID,
                            trans_info,
                            None,
                            "generic",
                        ],
                    ]
                ],
                separators=(",", ":"),
            ),
        )
        return rpc

    def _pick_service_url(self) -> str:
        """
        Pick a service url
        """
        if len(self.service_urls) == 1:
            return self.service_urls[0]
        return random.choice(self.service_urls)

    async def _translate(
        self, text: str, dest: str, src: str
    ) -> typing.Tuple[str, aiohttp.ClientResponse]:
        """
        Translate protected method
        """
        url = urls.TRANSLATE_RPC.format(host=self._pick_service_url())
        data = {
            "f.req": await self._build_rpc_request(text, dest, src),
        }
        params = {
            "rpcids": RPC_ID,
            "bl": "boq_translate-webserver_20201207.13_p0",
            "soc-app": 1,
            "soc-platform": 1,
            "soc-device": 1,
            "rt": "c",
        }
        request = await self.session.post(url, params=params, data=data)

        if request.status != 200 and self.raise_exception:
            raise Exception(
                f"""Unexpected status code "{request.status}" from {self.service_urls}"""
            )
        text = await request.text()
        return text, request

    async def _parse_extra_data(self, data: list) -> dict:
        """
        Parsing extra data to be returned to the user
        """
        response_parts_name_mapping = {
            0: "translation",
            1: "all-translations",
            2: "original-language",
            5: "possible-translations",
            6: "confidence",
            7: "possible-mistakes",
            8: "language",
            11: "synonyms",
            12: "definitions",
            13: "examples",
            14: "see-also",
        }

        extra = {}

        for index, category in response_parts_name_mapping.items():
            extra[category] = (
                data[index] if (index < len(data) and data[index]) else None
            )

        return extra

    async def translate(
        self, text: str, dest: str = "en", src: str = "auto"
    ) -> Translated:
        """
        Translate text
        """
        dest = dest.lower().split("_", 1)[0]
        src = src.lower().split("_", 1)[0]

        if src != "auto" and src not in LANGUAGES:
            if src in SPECIAL_CASES:
                src = SPECIAL_CASES[src]
            elif src in LANGCODES:
                src = LANGCODES[src]
            else:
                raise ValueError(f"Invalid Source Language: {src}")

        if dest not in LANGUAGES:
            if dest in SPECIAL_CASES:
                dest = SPECIAL_CASES[dest]
            elif dest in LANGCODES:
                dest = LANGCODES[dest]
            else:
                raise ValueError(f"Invalid Destination Language: {dest}")

        origin = text
        data, response = await self._translate(text, dest, src)

        token_found = False
        square_bracket_counts = [0, 0]
        resp = ""
        for line in data.split("\n"):
            token_found = token_found or f'"{RPC_ID}"' in line[:30]
            if not token_found:
                continue

            is_in_string = False
            for index, char in enumerate(line):
                if char == '"' and line[max(0, index - 1)] != "\\":
                    is_in_string = not is_in_string
                if not is_in_string:
                    if char == "[":
                        square_bracket_counts[0] += 1
                    elif char == "]":
                        square_bracket_counts[1] += 1

            resp += line
            if square_bracket_counts[0] == square_bracket_counts[1]:
                break

        data = await self.loop.run_in_executor(None, json.loads, resp)
        parsed = await self.loop.run_in_executor(None, json.loads, data[0][2])

        should_spacing = parsed[1][0][0][3]
        translated_parts = list(
            map(
                lambda part: TranslatedPart(part[0], part[1] if len(part) >= 2 else []),
                parsed[1][0][0][5],
            )
        )
        translated = (" " if should_spacing else "").join(
            map(lambda part: part.text, translated_parts)
        )

        if src == "auto":
            try:
                src = parsed[2]
            except:
                pass
        if src == "auto":
            try:
                src = parsed[0][2]
            except:
                pass

        # currently not available
        confidence = None

        origin_pronunciation = None
        try:
            origin_pronunciation = parsed[0][0]
        except:
            pass

        pronunciation = None
        try:
            pronunciation = parsed[1][0][0][1]
        except:
            pass

        extra_data = {
            "confidence": confidence,
            "parts": translated_parts,
            "origin_pronunciation": origin_pronunciation,
            "parsed": parsed,
        }
        result = Translated(
            src=src,
            dest=dest,
            origin=origin,
            text=translated,
            pronunciation=pronunciation,
            parts=translated_parts,
            extra_data=extra_data,
            response=response,
        )
        return result

    async def detect(self, text: str) -> Detected:
        """
        Detect a language
        """
        translated = await self.translate(text, src="auto", dest="en")
        result = Detected(
            lang=translated.src,
            confidence=translated.extra_data.get("confidence", None),
            response=translated._response,
        )
        return result
