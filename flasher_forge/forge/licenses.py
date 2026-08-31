"""
flasher_forge.forge.licenses
=============================

LICENSE file text for the four license choices.  MIT and Apache-2.0 apply their
standard boilerplate; GPL-3.0 uses the FSF's recommended notice; the proprietary
option produces an all-rights-reserved notice.  For GPL-3.0 and Apache-2.0 the
full legal text is long and version-stable, so the generated LICENSE carries the
official notice and points to the canonical full text (the accepted practice for
those licenses' "how to apply" instructions).
"""

from __future__ import annotations

MIT = """MIT License

Copyright (c) {year} {author}

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

GPL3 = """{author}'s flasher project
Copyright (C) {year} {author}

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with
this program. If not, see <https://www.gnu.org/licenses/>.

The full text of the GNU General Public License version 3 is available at
https://www.gnu.org/licenses/gpl-3.0.txt and should be distributed with this
software as a file named COPYING.
"""

APACHE2 = """Copyright {year} {author}

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

The full text of the Apache License, Version 2.0 is available at
http://www.apache.org/licenses/LICENSE-2.0.txt and should be distributed with
this software as a file named LICENSE-2.0.txt.
"""

PROPRIETARY = """Copyright (c) {year} {author}. All rights reserved.

This software and its firmware images are proprietary and confidential. No part
of this software may be copied, modified, distributed, reverse-engineered, or
used to create derivative works without the express prior written permission of
the copyright holder.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED. IN NO EVENT SHALL THE COPYRIGHT HOLDER BE LIABLE FOR ANY CLAIM,
DAMAGES OR OTHER LIABILITY ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
"""

_TEXTS = {
    "MIT": MIT,
    "GPL-3.0": GPL3,
    "Apache-2.0": APACHE2,
    "proprietary-closed": PROPRIETARY,
}


def render(license_id: str, year: int, author: str) -> str:
    tpl = _TEXTS.get(license_id, MIT)
    return tpl.format(year=year, author=author)
