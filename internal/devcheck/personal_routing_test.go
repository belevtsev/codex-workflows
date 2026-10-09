package devcheck

import (
	"path/filepath"
	"testing"
)

func TestPersonalRoutingFixturesKeepExpectedAnswersSeparate(t *testing.T) {
	root := filepath.Join("testdata", "personal-skill-routing")
	fixtures, err := decodeRoutingFixture[routingFixtures](filepath.Join(root, "oracles.json"))
	if err != nil {
		t.Fatal(err)
	}
	if err := validateRoutingFixtures(filepath.Join("..", ".."), root, fixtures); err != nil {
		t.Fatal(err)
	}
}
