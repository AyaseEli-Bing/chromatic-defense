// tdgo: 塔防排行榜（Go + SQLite），通过 cgo c-shared 导出 C ABI。
package main

/*
#include <stdlib.h>
*/
import "C"

import (
	"database/sql"
	"encoding/json"
	"unsafe"

	_ "modernc.org/sqlite"
)

var db *sql.DB

//export gr_init
func gr_init(path *C.char) C.int {
	p := C.GoString(path)
	d, err := sql.Open("sqlite", p)
	if err != nil {
		return -1
	}
	_, err = d.Exec(`CREATE TABLE IF NOT EXISTS scores(
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		name TEXT NOT NULL,
		score INTEGER NOT NULL,
		wave INTEGER NOT NULL,
		ts TEXT DEFAULT (datetime('now','localtime'))
	)`)
	if err != nil {
		d.Close()
		return -1
	}
	db = d
	return 0
}

//export gr_add_score
func gr_add_score(name *C.char, score, wave C.int) C.int {
	if db == nil {
		return -1
	}
	_, err := db.Exec("INSERT INTO scores(name, score, wave) VALUES(?,?,?)",
		C.GoString(name), int(score), int(wave))
	if err != nil {
		return -1
	}
	return 0
}

type Score struct {
	Name  string `json:"name"`
	Score int    `json:"score"`
	Wave  int    `json:"wave"`
	Ts    string `json:"ts"`
}

//export gr_top10
func gr_top10() *C.char {
	if db == nil {
		return nil
	}
	rows, err := db.Query("SELECT name, score, wave, ts FROM scores ORDER BY score DESC, ts ASC LIMIT 10")
	if err != nil {
		return nil
	}
	defer rows.Close()
	scores := []Score{}
	for rows.Next() {
		var s Score
		if err := rows.Scan(&s.Name, &s.Score, &s.Wave, &s.Ts); err != nil {
			continue
		}
		scores = append(scores, s)
	}
	b, _ := json.Marshal(scores)
	return C.CString(string(b))
}

//export gr_free
func gr_free(p *C.char) {
	if p != nil {
		C.free(unsafe.Pointer(p))
	}
}

//export gr_close
func gr_close() {
	if db != nil {
		db.Close()
		db = nil
	}
}

func main() {}
